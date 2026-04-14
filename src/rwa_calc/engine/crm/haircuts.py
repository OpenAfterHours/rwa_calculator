"""
Collateral haircut calculator for credit risk mitigation.

Pipeline position:
    Classifier -> CRMProcessor -> HaircutCalculator -> SA/IRB Calculators

Key responsibilities:
- Apply supervisory haircuts by collateral type, CQS, and maturity
- Framework-conditional logic: CRR (Art. 224) vs Basel 3.1 (CRE22.52-53)
- FX mismatch haircuts (8%, same under both frameworks)
- Art. 227 zero-haircut conditions for repo-style transactions
- Maturity mismatch adjustments (CRR Art. 237-238)
- Art. 237(2) ineligibility: original maturity <1yr, 1-day M floor exposures

References:
    CRR Art. 224: Supervisory haircuts (3 maturity bands)
    CRR Art. 227: Zero volatility adjustments for qualifying repos/SFTs
    CRR Art. 237: Maturity mismatch — eligibility conditions
    CRR Art. 238: Maturity mismatch — adjustment formula (CVAM)
    CRE22.52-53: Basel 3.1 supervisory haircuts (5 maturity bands, higher equity/long-dated)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.data.schemas import (
    REAL_ESTATE_COLLATERAL_TYPES,
    RECEIVABLE_COLLATERAL_TYPES,
)
from rwa_calc.data.tables.crm_supervisory import ZERO_HAIRCUT_MAX_SOVEREIGN_CQS
from rwa_calc.data.tables.haircuts import (
    FX_HAIRCUT,
    calculate_adjusted_collateral_value,
    calculate_maturity_mismatch_adjustment,
    get_haircut_table,
    lookup_collateral_haircut,
    lookup_fx_haircut,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


@dataclass
class HaircutResult:
    """Result of haircut calculation for collateral."""

    original_value: Decimal
    collateral_haircut: Decimal
    fx_haircut: Decimal
    maturity_adjustment: Decimal
    adjusted_value: Decimal
    description: str


class HaircutCalculator:
    """
    Calculate and apply haircuts to collateral.

    Supports both CRR and Basel 3.1 frameworks with liquidation period scaling.

    Base haircuts (10-day liquidation period):

    CRR (Art. 224) — 3 maturity bands:
    - Government bonds: 0.5% - 6%
    - Corporate bonds: 1% - 8%
    - Equity (main index): 15%, (other): 25%
    - Gold: 15%

    Basel 3.1 (PRA PS1/26 Art. 224) — 5 maturity bands:
    - Government bonds: 0.5% - 12% (higher for long-dated CQS 2-3)
    - Corporate bonds: 1% - 15% (significantly higher for long-dated)
    - Equity (main index): 20%, (other): 30%
    - Gold: 20%

    FX mismatch: 8% (10-day base, same under both frameworks).

    Liquidation period scaling (Art. 226(2)): H_m = H_10 × sqrt(T_m / 10)
    - 5-day (repos): haircut × 0.7071
    - 10-day (capital market): no scaling [default]
    - 20-day (secured lending): haircut × 1.4142
    """

    def __init__(self, is_basel_3_1: bool = False) -> None:
        """Initialize haircut calculator with lookup tables.

        Args:
            is_basel_3_1: True for Basel 3.1 haircuts, False for CRR
        """
        self._is_basel_3_1 = is_basel_3_1
        self._haircut_table = get_haircut_table(is_basel_3_1=is_basel_3_1)

    def apply_haircuts(
        self,
        collateral: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply haircuts to collateral.

        Expects exposure_currency and exposure_maturity columns to already be
        present on collateral (joined via _join_collateral_to_lookups before calling).

        Args:
            collateral: Collateral data with market values, exposure_currency, exposure_maturity
            config: Calculation configuration

        Returns:
            LazyFrame with haircut-adjusted collateral values
        """
        is_b31 = config.is_basel_3_1

        # Add maturity band for bond haircut lookup
        collateral = collateral.with_columns(
            [self._maturity_band_expression(is_b31).alias("maturity_band")]
        )

        # Calculate collateral-specific haircut based on type
        collateral = self._apply_collateral_haircuts(collateral, is_b31)

        # Scale collateral haircut and FX haircut by liquidation period (Art. 226(2))
        # H_m = H_10 × sqrt(T_m / 10)
        schema = collateral.collect_schema()
        has_liq_period = "liquidation_period_days" in schema.names()

        if has_liq_period:
            liq = pl.col("liquidation_period_days").fill_null(10).cast(pl.Float64)
            scaling_factor = (liq / 10.0).sqrt()
        else:
            scaling_factor = pl.lit(1.0)

        # Scale collateral haircut by liquidation period
        # Non-financial collateral (real_estate, receivables, other_physical) uses Art. 230
        # HC values, not Art. 224 — do not scale those. However, the table join already
        # returns the correct base value; scaling only affects financial collateral and gold.
        if has_liq_period:
            collateral = collateral.with_columns(
                (pl.col("collateral_haircut") * scaling_factor).alias("collateral_haircut")
            )

        # Apply FX haircut (also subject to liquidation period scaling per Art. 224 Table 4)
        # Art. 227: zero-haircut repos waive ALL volatility adjustments including H_fx
        fx_base = float(FX_HAIRCUT)
        has_zero_flag = "_is_zero_haircut" in collateral.collect_schema().names()
        fx_expr = (
            pl.when(pl.col("currency") != pl.col("exposure_currency"))
            .then(pl.lit(fx_base) * scaling_factor)
            .otherwise(pl.lit(0.0))
        )
        if has_zero_flag:
            fx_expr = pl.when(pl.col("_is_zero_haircut")).then(pl.lit(0.0)).otherwise(fx_expr)
        collateral = collateral.with_columns([fx_expr.alias("fx_haircut")])

        # Calculate adjusted value after haircuts
        collateral = collateral.with_columns(
            [
                (
                    pl.col("market_value")
                    * (1.0 - pl.col("collateral_haircut") - pl.col("fx_haircut"))
                )
                .clip(lower_bound=0.0)
                .alias("value_after_haircut"),
            ]
        )

        # Zero out value for ineligible bonds (Art. 197 — CQS 5-6 govt, CQS 4-6 corp)
        if "_bond_ineligible" in collateral.collect_schema().names():
            collateral = collateral.with_columns(
                pl.when(pl.col("_bond_ineligible"))
                .then(pl.lit(0.0))
                .otherwise(pl.col("value_after_haircut"))
                .alias("value_after_haircut")
            )
            # Also enforce is_eligible_financial_collateral = False for ineligible bonds
            if "is_eligible_financial_collateral" in collateral.collect_schema().names():
                collateral = collateral.with_columns(
                    pl.when(pl.col("_bond_ineligible"))
                    .then(pl.lit(False))
                    .otherwise(pl.col("is_eligible_financial_collateral"))
                    .alias("is_eligible_financial_collateral")
                )
            collateral = collateral.drop("_bond_ineligible")

        # Clean up Art. 227 temp column
        if "_is_zero_haircut" in collateral.collect_schema().names():
            collateral = collateral.drop("_is_zero_haircut")

        # Add haircut audit trail
        collateral = collateral.with_columns(
            [
                pl.concat_str(
                    [
                        pl.lit("MV="),
                        pl.col("market_value").round(0).cast(pl.String),
                        pl.lit("; Hc="),
                        (pl.col("collateral_haircut") * 100).round(1).cast(pl.String),
                        pl.lit("%; Hfx="),
                        (pl.col("fx_haircut") * 100).round(1).cast(pl.String),
                        pl.lit("%; Adj="),
                        pl.col("value_after_haircut").round(0).cast(pl.String),
                    ]
                ).alias("haircut_calculation"),
            ]
        )

        return collateral

    @staticmethod
    def _maturity_band_expression(is_basel_3_1: bool) -> pl.Expr:
        """Build Polars expression to classify residual maturity into bands.

        CRR: 3 bands (0-1y, 1-5y, 5y+)
        Basel 3.1: 5 bands (0-1y, 1-3y, 3-5y, 5-10y, 10y+)
        """
        mat = pl.col("residual_maturity_years")
        if is_basel_3_1:
            return (
                pl.when(mat.is_null())
                .then(pl.lit("10y_plus"))
                .when(mat <= 1.0)
                .then(pl.lit("0_1y"))
                .when(mat <= 3.0)
                .then(pl.lit("1_3y"))
                .when(mat <= 5.0)
                .then(pl.lit("3_5y"))
                .when(mat <= 10.0)
                .then(pl.lit("5_10y"))
                .otherwise(pl.lit("10y_plus"))
            )
        return (
            pl.when(mat.is_null())
            .then(pl.lit("5y_plus"))
            .when(mat <= 1.0)
            .then(pl.lit("0_1y"))
            .when(mat <= 5.0)
            .then(pl.lit("1_5y"))
            .otherwise(pl.lit("5y_plus"))
        )

    def _apply_collateral_haircuts(
        self,
        collateral: pl.LazyFrame,
        is_basel_3_1: bool = False,
    ) -> pl.LazyFrame:
        """Apply collateral-type-specific haircuts via lookup table join.

        Art. 227 zero-haircut: when ``qualifies_for_zero_haircut`` is True and the
        collateral type is eligible (cash/deposit or CQS ≤ 1 sovereign bond), both
        H_c and H_fx are set to 0%.  The ``_is_zero_haircut`` flag is propagated so
        ``apply_haircuts`` can also zero the FX haircut.
        """
        # Ensure issuer_type column exists for bond type normalization.
        collateral = ensure_columns(
            collateral,
            {"issuer_type": ColumnSpec(pl.String, required=False)},
        )
        schema = collateral.collect_schema()

        # Art. 227: determine whether zero-haircut flag column is available
        has_zero_haircut_col = "qualifies_for_zero_haircut" in schema.names()
        # Art. 224 Table 3/4: is_main_index distinguishes main-index vs other-listed equity
        has_main_index_col = "is_main_index" in schema.names()

        # Normalize collateral type and build sentinel join keys
        bond_types = pl.col("_lookup_type").is_in(["govt_bond", "corp_bond"])
        is_equity = pl.col("_lookup_type") == "equity"

        # Equity main-index lookup: prefer is_main_index when available,
        # fall back to is_eligible_financial_collateral for backward compatibility.
        if has_main_index_col:
            _equity_main_index_expr = pl.col("is_main_index").fill_null(True).cast(pl.Int8)
        else:
            _equity_main_index_expr = (
                pl.col("is_eligible_financial_collateral").fill_null(False).cast(pl.Int8)
            )

        collateral = collateral.with_columns(
            [self._normalize_collateral_type_expr().alias("_lookup_type")]
        ).with_columns(
            [
                pl.when(bond_types)
                .then(pl.col("issuer_cqs").fill_null(-1))
                .otherwise(pl.lit(-1))
                .cast(pl.Int8)
                .alias("_lookup_cqs"),
                pl.when(bond_types)
                .then(pl.col("maturity_band").fill_null("__none__"))
                .otherwise(pl.lit("__none__"))
                .alias("_lookup_maturity_band"),
                pl.when(is_equity)
                .then(_equity_main_index_expr)
                .otherwise(pl.lit(-1).cast(pl.Int8))
                .alias("_lookup_is_main_index"),
            ]
        )

        # Prepare haircut table with matching sentinels
        ht = self._haircut_table.lazy().with_columns(
            [
                pl.col("cqs").fill_null(-1).cast(pl.Int8),
                pl.col("maturity_band").fill_null("__none__"),
                pl.col("is_main_index").cast(pl.Int8).fill_null(-1),
            ]
        )

        # Left join to look up haircut values
        collateral = collateral.join(
            ht.select(["collateral_type", "cqs", "maturity_band", "is_main_index", "haircut"]),
            left_on=[
                "_lookup_type",
                "_lookup_cqs",
                "_lookup_maturity_band",
                "_lookup_is_main_index",
            ],
            right_on=["collateral_type", "cqs", "maturity_band", "is_main_index"],
            how="left",
            suffix="_ht",
        )

        # Bond eligibility check per CRR Art. 197
        # Govt bonds: CQS 1-4 eligible (Art. 197(1)(b)), CQS 5-6/unrated ineligible
        # Corp/institution bonds: CQS 1-3 eligible (Art. 197(1)(d)), CQS 4-6/unrated ineligible
        is_govt = pl.col("_lookup_type") == "govt_bond"
        is_corp = pl.col("_lookup_type") == "corp_bond"
        cqs_val = pl.col("issuer_cqs")
        _ineligible_bond = (is_govt & ((cqs_val >= 5) | cqs_val.is_null())) | (
            is_corp & ((cqs_val >= 4) | cqs_val.is_null())
        )

        # Art. 227(2)(a): eligible for zero haircut if cash/deposit or CQS ≤ 1 sovereign bond
        _zero_type_eligible = pl.col("_lookup_type").is_in(["cash"]) | (
            (pl.col("_lookup_type") == "govt_bond")
            & pl.col("issuer_cqs").fill_null(99).le(ZERO_HAIRCUT_MAX_SOVEREIGN_CQS)
        )

        if has_zero_haircut_col:
            _is_art227 = pl.col("qualifies_for_zero_haircut").fill_null(False) & _zero_type_eligible
        else:
            _is_art227 = pl.lit(False)

        # Art. 232: life insurance uses surrender value directly — no supervisory haircut
        _is_life_insurance = pl.col("_lookup_type") == "life_insurance"

        # Assign haircut: life insurance 0% → Art. 227 zero → ineligible bond 100% → lookup → 40%
        collateral = collateral.with_columns(
            [
                _ineligible_bond.alias("_bond_ineligible"),
                _is_art227.alias("_is_zero_haircut"),
                pl.when(_is_life_insurance)
                .then(pl.lit(0.0))
                .when(_is_art227)
                .then(pl.lit(0.0))
                .when(_ineligible_bond)
                .then(pl.lit(1.0))
                .otherwise(pl.col("haircut").fill_null(0.40))
                .alias("collateral_haircut"),
            ]
        ).drop(
            [
                "_lookup_type",
                "_lookup_cqs",
                "_lookup_maturity_band",
                "_lookup_is_main_index",
                "haircut",
            ]
        )

        return collateral

    @staticmethod
    def _normalize_collateral_type_expr() -> pl.Expr:
        """Map collateral_type aliases to canonical types for haircut table lookup."""
        ct = pl.col("collateral_type").str.to_lowercase()
        return (
            pl.when(ct.is_in(["cash", "deposit", "credit_linked_note"]))
            .then(pl.lit("cash"))
            .when(ct == "gold")
            .then(pl.lit("gold"))
            .when(ct == "life_insurance")
            .then(pl.lit("life_insurance"))
            .when(
                ct.is_in(["govt_bond", "sovereign_bond", "government_bond", "gilt"])
                | ((ct == "bond") & (pl.col("issuer_type").str.to_lowercase() == "sovereign"))
            )
            .then(pl.lit("govt_bond"))
            .when(ct.is_in(["corp_bond", "corporate_bond"]))
            .then(pl.lit("corp_bond"))
            .when(ct.is_in(["equity", "shares", "stock"]))
            .then(pl.lit("equity"))
            .when(ct.is_in(RECEIVABLE_COLLATERAL_TYPES))
            .then(pl.lit("receivables"))
            .when(ct.is_in(REAL_ESTATE_COLLATERAL_TYPES))
            .then(pl.lit("real_estate"))
            .otherwise(pl.lit("other_physical"))
        )

    def apply_maturity_mismatch(
        self,
        collateral: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply maturity mismatch adjustment per CRR Art. 237-238.

        Art. 237(2) ineligibility conditions (protection zeroed when mismatch exists):
        - (a) Residual maturity < 3 months (existing check)
        - (b) Original maturity of protection < 1 year
        - Art. 162(3) exposures with 1-day IRB maturity floor: ANY mismatch makes
          protection ineligible (repos/SFTs with daily margining)

        Formula (Art. 238): CVAM = CVA × (t - 0.25) / (T - 0.25)
        where t = collateral residual maturity, T = min(exposure residual maturity, 5).

        Args:
            collateral: Collateral with value_after_haircut, residual_maturity_years,
                and exposure_maturity (Date) columns. Optionally:
                original_maturity_years (Float64) and
                exposure_has_one_day_maturity_floor (Boolean).
            config: Calculation configuration (provides reporting_date)

        Returns:
            LazyFrame with maturity-adjusted collateral values
        """
        reporting_date = config.reporting_date
        coll_schema = collateral.collect_schema()

        # Derive exposure maturity in years from the Date column, capped at 5y, floored at 0.25y
        exposure_maturity_years_expr = (
            (
                (pl.col("exposure_maturity").cast(pl.Date) - pl.lit(reporting_date))
                .dt.total_days()
                .cast(pl.Float64)
                / 365.25
            )
            .clip(lower_bound=0.25, upper_bound=5.0)
            .fill_null(5.0)
        )

        prep_cols = [
            pl.col("residual_maturity_years").fill_null(10.0).alias("coll_maturity"),
            exposure_maturity_years_expr.alias("_exposure_maturity_years"),
        ]

        # Art. 237(2): original maturity of protection — null defaults to >= 1yr (permissive)
        if "original_maturity_years" in coll_schema.names():
            prep_cols.append(
                pl.col("original_maturity_years").fill_null(10.0).alias("_orig_maturity")
            )
        else:
            prep_cols.append(pl.lit(10.0).alias("_orig_maturity"))

        # Art. 162(3): 1-day maturity floor flag — null/absent defaults to False (permissive)
        if "exposure_has_one_day_maturity_floor" in coll_schema.names():
            prep_cols.append(
                pl.col("exposure_has_one_day_maturity_floor")
                .fill_null(False)
                .alias("_has_1d_floor")
            )
        else:
            prep_cols.append(pl.lit(False).alias("_has_1d_floor"))

        collateral = collateral.with_columns(prep_cols)

        # Determine whether a maturity mismatch exists (collateral < exposure)
        has_mismatch = pl.col("coll_maturity") < pl.col("_exposure_maturity_years")

        # Calculate maturity mismatch adjustment per Art. 237-238
        collateral = collateral.with_columns(
            [
                # No adjustment when collateral maturity >= exposure maturity
                pl.when(~has_mismatch)
                .then(pl.lit(1.0))
                # Art. 237(2)(a): No protection when collateral maturity < 3 months
                .when(pl.col("coll_maturity") < 0.25)
                .then(pl.lit(0.0))
                # Art. 237(2): Original maturity of protection < 1 year → ineligible
                .when(pl.col("_orig_maturity") < 1.0)
                .then(pl.lit(0.0))
                # Art. 162(3)/237(2): 1-day M floor exposure → any mismatch makes
                # protection ineligible (repos/SFTs with daily margining)
                .when(pl.col("_has_1d_floor"))
                .then(pl.lit(0.0))
                # CVAM = (t - 0.25) / (T - 0.25) where T = exposure maturity capped at 5y
                .otherwise(
                    (pl.col("coll_maturity") - 0.25) / (pl.col("_exposure_maturity_years") - 0.25)
                )
                .alias("maturity_adjustment_factor"),
            ]
        )

        # Apply maturity adjustment
        collateral = collateral.with_columns(
            [
                (pl.col("value_after_haircut") * pl.col("maturity_adjustment_factor")).alias(
                    "value_after_maturity_adj"
                ),
            ]
        )

        return collateral.drop(["_exposure_maturity_years", "_orig_maturity", "_has_1d_floor"])

    def calculate_single_haircut(
        self,
        collateral_type: str,
        market_value: Decimal,
        collateral_currency: str,
        exposure_currency: str,
        cqs: int | None = None,
        residual_maturity_years: float | None = None,
        is_main_index: bool = False,
        collateral_maturity_years: float | None = None,
        exposure_maturity_years: float | None = None,
        original_maturity_years: float | None = None,
        has_one_day_maturity_floor: bool = False,
        liquidation_period_days: int = 10,
        qualifies_for_zero_haircut: bool = False,
    ) -> HaircutResult:
        """
        Calculate haircut for a single collateral item (convenience method).

        Args:
            collateral_type: Type of collateral
            market_value: Market value of collateral
            collateral_currency: Currency of collateral
            exposure_currency: Currency of exposure
            cqs: Credit quality step of issuer
            residual_maturity_years: Residual maturity for bonds
            is_main_index: Whether equity is on main index
            collateral_maturity_years: For maturity mismatch
            exposure_maturity_years: For maturity mismatch
            original_maturity_years: Original contract term of protection (Art. 237(2))
            has_one_day_maturity_floor: Art. 162(3) 1-day M floor exposure
            liquidation_period_days: Liquidation period in business days (default 10)
            qualifies_for_zero_haircut: Art. 227 — institution certifies all 8 conditions met

        Returns:
            HaircutResult with all haircut details
        """
        # Art. 227: zero-haircut for qualifying repos — check type eligibility
        if qualifies_for_zero_haircut:
            norm = collateral_type.lower()
            is_cash = norm in ("cash", "deposit")
            is_eligible_sovereign = norm in (
                "govt_bond",
                "sovereign_bond",
                "government_bond",
                "gilt",
            ) and (cqs is not None and cqs <= ZERO_HAIRCUT_MAX_SOVEREIGN_CQS)
            if is_cash or is_eligible_sovereign:
                # All volatility adjustments zeroed: H_c = 0%, H_e = 0%, H_fx = 0%
                adjusted = market_value
                # Still apply maturity mismatch if applicable
                maturity_adj = Decimal("1.0")
                if collateral_maturity_years and exposure_maturity_years:
                    adjusted, _ = calculate_maturity_mismatch_adjustment(
                        collateral_value=adjusted,
                        collateral_maturity_years=collateral_maturity_years,
                        exposure_maturity_years=exposure_maturity_years,
                        original_maturity_years=original_maturity_years,
                        has_one_day_maturity_floor=has_one_day_maturity_floor,
                    )
                    if adjusted > Decimal("0") and market_value > Decimal("0"):
                        maturity_adj = adjusted / market_value
                return HaircutResult(
                    original_value=market_value,
                    collateral_haircut=Decimal("0.0"),
                    fx_haircut=Decimal("0.0"),
                    maturity_adjustment=maturity_adj,
                    adjusted_value=adjusted,
                    description=(
                        f"MV={market_value:,.0f}; Art.227 zero-haircut "
                        f"(type={collateral_type}); Adj={adjusted:,.0f}"
                    ),
                )

        # Art. 232: Life insurance — no supervisory haircut (surrender value IS the value)
        if collateral_type.lower() == "life_insurance":
            fx_h = lookup_fx_haircut(
                exposure_currency, collateral_currency, liquidation_period_days
            )
            adjusted = market_value * (1 - fx_h)
            return HaircutResult(
                original_value=market_value,
                collateral_haircut=Decimal("0"),
                fx_haircut=fx_h,
                maturity_adjustment=Decimal("1.0"),
                adjusted_value=adjusted,
                description=(
                    f"MV={market_value:,.0f}; Art.232 life insurance "
                    f"Hc=0%; Hfx={fx_h:.1%}; Adj={adjusted:,.0f}"
                ),
            )

        # Art. 218: CLN → treat as cash collateral
        if collateral_type.lower() == "credit_linked_note":
            collateral_type = "cash"

        # Get collateral haircut scaled for liquidation period (None = ineligible per Art. 197)
        coll_haircut = lookup_collateral_haircut(
            collateral_type=collateral_type,
            cqs=cqs,
            residual_maturity_years=residual_maturity_years,
            is_main_index=is_main_index,
            is_basel_3_1=self._is_basel_3_1,
            liquidation_period_days=liquidation_period_days,
        )

        # Ineligible bonds: zero adjusted value
        if coll_haircut is None:
            return HaircutResult(
                original_value=market_value,
                collateral_haircut=Decimal("1.0"),
                fx_haircut=Decimal("0.0"),
                maturity_adjustment=Decimal("0.0"),
                adjusted_value=Decimal("0"),
                description=(
                    f"MV={market_value:,.0f}; INELIGIBLE per Art. 197 "
                    f"(type={collateral_type}, CQS={cqs})"
                ),
            )

        # Get FX haircut (scaled for liquidation period)
        fx_haircut = lookup_fx_haircut(
            exposure_currency, collateral_currency, liquidation_period_days
        )

        # Calculate adjusted value after haircuts
        adjusted = calculate_adjusted_collateral_value(
            collateral_value=market_value,
            collateral_haircut=coll_haircut,
            fx_haircut=fx_haircut,
        )

        # Apply maturity mismatch if applicable
        maturity_adj = Decimal("1.0")
        if collateral_maturity_years and exposure_maturity_years:
            adjusted, _ = calculate_maturity_mismatch_adjustment(
                collateral_value=adjusted,
                collateral_maturity_years=collateral_maturity_years,
                exposure_maturity_years=exposure_maturity_years,
                original_maturity_years=original_maturity_years,
                has_one_day_maturity_floor=has_one_day_maturity_floor,
            )
            if adjusted > Decimal("0"):
                maturity_adj = adjusted / (market_value * (1 - coll_haircut - fx_haircut))

        description = (
            f"MV={market_value:,.0f}; Hc={coll_haircut:.1%}; "
            f"Hfx={fx_haircut:.1%}; Adj={adjusted:,.0f}"
        )

        return HaircutResult(
            original_value=market_value,
            collateral_haircut=coll_haircut,
            fx_haircut=fx_haircut,
            maturity_adjustment=maturity_adj,
            adjusted_value=adjusted,
            description=description,
        )


def create_haircut_calculator(is_basel_3_1: bool = False) -> HaircutCalculator:
    """
    Create a haircut calculator instance.

    Args:
        is_basel_3_1: True for Basel 3.1 haircuts, False for CRR

    Returns:
        HaircutCalculator ready for use
    """
    return HaircutCalculator(is_basel_3_1=is_basel_3_1)
