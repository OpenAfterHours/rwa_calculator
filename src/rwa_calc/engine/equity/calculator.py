"""
Equity Calculator for Equity Exposure RWA.

Implements framework-dependent approaches:
- CRR Article 133: Standardised Approach (SA) — 0%/100%/250%/400%
- CRR Article 155: IRB Simple Risk Weight Method — 190%/290%/370%
- Basel 3.1 Art. 133(3)-(6): SA only — 0%/100%/250%/400% (IRB removed)

Pipeline position:
    CRMProcessor -> EquityCalculator -> Aggregation

Key responsibilities:
- Determine equity risk weights based on equity type and framework
- Handle diversified portfolio treatment for private equity
- Apply transitional floor (PRA Rules 4.1-4.10) during phase-in
- Calculate RWA = EAD x RW
- Build audit trail of calculations

Basel 3.1 key changes from CRR:
- Listed/exchange-traded: 100% -> 250% (Art. 133(3))
- CIU fallback: 150% -> 250% (Art. 132(2))
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
from rwa_calc.domain.enums import ApproachType

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


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

        if approach == "irb_simple":
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
                approach="sa",
                errors=[],
            )

        approach = self._determine_approach(config)

        exposures = self._prepare_columns(exposures, config)
        exposures = self._resolve_look_through_rw(exposures, data.ciu_holdings, config)

        if approach == "irb_simple":
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

    def _determine_approach(self, config: CalculationConfig) -> str:
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
            "sa" for Article 133, "irb_simple" for Article 155
        """
        # Basel 3.1: IRB equity removed — all equity uses SA (CRE20.58-62)
        if config.is_basel_3_1:
            return "sa"

        # CRR: Check if firm has any IRB permissions beyond SA
        # If permissions dict is empty, it's SA-only
        if not config.irb_permissions.permissions:
            return "sa"

        # Check if any exposure class has FIRB or AIRB permission
        for _exposure_class, approaches in config.irb_permissions.permissions.items():
            if ApproachType.FIRB in approaches or ApproachType.AIRB in approaches:
                return "irb_simple"

        return "sa"

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

        schema = exposures.collect_schema()

        if "equity_type" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.lit("other").alias("equity_type"),
                ]
            )

        if "is_diversified_portfolio" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.lit(False).alias("is_diversified_portfolio"),
                ]
            )

        if "is_speculative" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.lit(False).alias("is_speculative"),
                ]
            )

        if "is_exchange_traded" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.lit(False).alias("is_exchange_traded"),
                ]
            )

        if "is_government_supported" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.lit(False).alias("is_government_supported"),
                ]
            )

        if "ciu_approach" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.lit(None).cast(pl.Utf8).alias("ciu_approach"),
                ]
            )

        if "ciu_mandate_rw" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.lit(None).cast(pl.Float64).alias("ciu_mandate_rw"),
                ]
            )

        if "ciu_third_party_calc" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.lit(None).cast(pl.Boolean).alias("ciu_third_party_calc"),
                ]
            )

        if "fund_reference" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.lit(None).cast(pl.Utf8).alias("fund_reference"),
                ]
            )

        if "ciu_look_through_rw" not in schema.names():
            exposures = exposures.with_columns(
                [
                    pl.lit(None).cast(pl.Float64).alias("ciu_look_through_rw"),
                ]
            )

        return exposures

    def _resolve_look_through_rw(
        self,
        exposures: pl.LazyFrame,
        ciu_holdings: pl.LazyFrame | None,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Resolve look-through risk weights for CIU exposures (Art. 132).

        Joins CIU holdings to SA risk weight tables, aggregates a
        value-weighted effective RW per fund, and sets ciu_look_through_rw.

        If no holdings are available, exposures are returned unchanged
        and the look-through CIU falls back to 250% in the when-chain.
        """
        if ciu_holdings is None:
            return exposures

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
        # Use sentinel -1 for null CQS to allow join
        holdings_with_rw = (
            ciu_holdings.with_columns(
                pl.col("cqs").fill_null(-1).cast(pl.Int8).alias("cqs"),
                pl.col("exposure_class").str.to_uppercase().alias("exposure_class"),
            )
            .join(
                rw_table.with_columns(
                    pl.col("cqs").fill_null(-1).cast(pl.Int8).alias("cqs"),
                ),
                on=["exposure_class", "cqs"],
                how="left",
            )
            .with_columns(
                pl.col("risk_weight").fill_null(1.00).alias("holding_rw"),
            )
        )

        # Aggregate to effective RW per fund
        fund_rw = (
            holdings_with_rw.group_by("fund_reference")
            .agg(
                (pl.col("holding_value") * pl.col("holding_rw")).sum().alias("_weighted_sum"),
                pl.col("holding_value").sum().alias("_total_value"),
            )
            .with_columns(
                pl.when(pl.col("_total_value") > 0)
                .then(pl.col("_weighted_sum") / pl.col("_total_value"))
                .otherwise(pl.lit(2.50))
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
            CIU via Art. 132 (150% fallback for regulated-exchange CIU)
        Basel 3.1 Art. 133(3)-(6): 250% / 400% / 100% (legislative) / 150% (sub debt)
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
        - CIU: Art. 132 treatment (150% fallback, look-through, mandate-based)
        - All other equity: 100% (Art. 133(2) flat)

        Note: PE/VC qualifying as high-risk is routed to Art. 128 (150%) via the
        classifier's HIGH_RISK exposure class, not through this equity calculator.
        """
        return exposures.with_columns(
            [
                pl.when(pl.col("equity_type").str.to_lowercase() == "central_bank")
                .then(pl.lit(0.00))
                # CIU: approach-aware risk weights (Art. 132-132C)
                .when(
                    (pl.col("equity_type").str.to_lowercase() == "ciu")
                    & (pl.col("ciu_approach") == "fallback")
                )
                .then(pl.lit(1.50))  # 150% CRR Art. 132(2) fallback
                .when(
                    (pl.col("equity_type").str.to_lowercase() == "ciu")
                    & (pl.col("ciu_approach") == "mandate_based")
                )
                .then(
                    pl.col("ciu_mandate_rw").fill_null(1.50)
                    * pl.when(pl.col("ciu_third_party_calc").fill_null(False))
                    .then(pl.lit(1.2))
                    .otherwise(pl.lit(1.0))
                )  # Art. 132A, 1.2x for third-party (Art. 132(4))
                .when(
                    (pl.col("equity_type").str.to_lowercase() == "ciu")
                    & (pl.col("ciu_approach") == "look_through")
                )
                .then(pl.col("ciu_look_through_rw").fill_null(1.50))  # Art. 132
                .when(pl.col("equity_type").str.to_lowercase() == "ciu")
                .then(pl.lit(1.50))  # CIU default: Art. 132(2) fallback
                # Art. 133(2): all other equity = 100%
                .otherwise(pl.lit(1.00))
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

        Risk weights:
        - Central bank: 0%  (Art. 133(6))
        - Government-supported (legislative programme): 100%
        - Speculative / higher risk: 400%  (Art. 133(4))
        - All other standard equity: 250%  (Art. 133(3))
        - CIU fallback: 250%  (Art. 132(2) under B31)

        Note: Subordinated debt / non-equity own funds = 150% (Art. 133(5))
        requires EquityType.SUBORDINATED_DEBT — not yet implemented.
        """
        return exposures.with_columns(
            [
                pl.when(pl.col("equity_type").str.to_lowercase() == "central_bank")
                .then(pl.lit(0.00))  # Art. 133(6): 0%
                .when(pl.col("is_speculative") == True)  # noqa: E712
                .then(pl.lit(4.00))  # Art. 133(4): 400% higher risk
                .when(pl.col("equity_type").str.to_lowercase() == "speculative")
                .then(pl.lit(4.00))  # Art. 133(4): 400% higher risk
                .when(pl.col("is_government_supported") == True)  # noqa: E712
                .then(pl.lit(1.00))  # Legislative programme: 100%
                .when(pl.col("equity_type").str.to_lowercase() == "government_supported")
                .then(pl.lit(1.00))  # Legislative programme: 100%
                # CIU: approach-aware risk weights (B31 Art. 132-132C)
                .when(
                    (pl.col("equity_type").str.to_lowercase() == "ciu")
                    & (pl.col("ciu_approach") == "fallback")
                )
                .then(pl.lit(2.50))  # B31 Art. 132(2): 250% fallback (was 150% CRR)
                .when(
                    (pl.col("equity_type").str.to_lowercase() == "ciu")
                    & (pl.col("ciu_approach") == "mandate_based")
                )
                .then(
                    pl.col("ciu_mandate_rw").fill_null(2.50)
                    * pl.when(pl.col("ciu_third_party_calc").fill_null(False))
                    .then(pl.lit(1.2))
                    .otherwise(pl.lit(1.0))
                )  # Art. 132A, 1.2x for third-party
                .when(
                    (pl.col("equity_type").str.to_lowercase() == "ciu")
                    & (pl.col("ciu_approach") == "look_through")
                )
                .then(pl.col("ciu_look_through_rw").fill_null(2.50))  # Art. 132
                .when(pl.col("equity_type").str.to_lowercase() == "ciu")
                .then(pl.lit(2.50))  # CIU default: 250%
                .otherwise(pl.lit(2.50))  # Art. 133(3): 250% standard
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
                .then(pl.lit(0.00))
                .when(
                    (pl.col("equity_type").str.to_lowercase() == "private_equity_diversified")
                    | (
                        (pl.col("equity_type").str.to_lowercase() == "private_equity")
                        & (pl.col("is_diversified_portfolio") == True)  # noqa: E712
                    )
                )
                .then(pl.lit(1.90))
                .when(pl.col("is_government_supported") == True)  # noqa: E712
                .then(pl.lit(1.90))
                .when(pl.col("equity_type").str.to_lowercase() == "government_supported")
                .then(pl.lit(1.90))
                .when(pl.col("is_exchange_traded") == True)  # noqa: E712
                .then(pl.lit(2.90))
                .when(pl.col("equity_type").str.to_lowercase() == "listed")
                .then(pl.lit(2.90))
                .when(pl.col("equity_type").str.to_lowercase() == "exchange_traded")
                .then(pl.lit(2.90))
                .otherwise(pl.lit(3.70))
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
        is_hr = (
            pl.col("is_speculative").fill_null(False)
            if "is_speculative" in schema.names()
            else pl.lit(False)
        )

        transitional_rw = pl.when(is_hr).then(pl.lit(float(hr_rw))).otherwise(pl.lit(float(std_rw)))

        return exposures.with_columns(
            pl.max_horizontal(pl.col("risk_weight"), transitional_rw).alias("risk_weight"),
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
        approach: str,
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

        article = "Art. 133 SA" if approach == "sa" else "Art. 155 IRB Simple"

        audit = audit.with_columns(
            [
                pl.concat_str(
                    [
                        pl.lit(f"Equity ({article}): Type="),
                        pl.col("equity_type"),
                        pl.lit(", RW="),
                        (pl.col("risk_weight") * 100).round(0).cast(pl.String),
                        pl.lit("%, RWA="),
                        pl.col("rwa").round(0).cast(pl.String),
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
