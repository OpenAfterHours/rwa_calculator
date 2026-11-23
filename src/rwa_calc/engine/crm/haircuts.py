"""
Collateral haircut calculator for credit risk mitigation.

Pipeline position:
    Classifier -> CRMProcessor -> HaircutCalculator -> SA/IRB Calculators

Key responsibilities:
- Apply supervisory haircuts by collateral type, CQS, and maturity
- Framework-conditional logic: CRR (Art. 224) vs Basel 3.1 (CRE22.52-53)
- FX mismatch haircuts (8%, same under both frameworks); a null collateral
  currency is a mismatch; non-financial collateral takes H_fx under Basel 3.1
  only (pack Feature ``fcm_hfx_applies_to_non_financial``, PS1/26 Art. 230(1)(b))
- Collateral residual maturity derived from ``maturity_date`` when not supplied
  (Art. 238(1))
- Art. 227 zero-haircut conditions for repo-style transactions
- Art. 229(1) claims ranking ahead on a property (``prior_charge_ltv``) deducted
  from its haircut value, floored at zero: MV (1 - HC - Hfx) - P, which is CRR's
  MV - P (property HC 0%, no Hfx) and PS1/26 Art. 229(1)(b)'s P / (1 - HC - Hfx)
  reduction carried into the ES
- Maturity mismatch adjustments (CRR Art. 237-238)
- Art. 237(2) ineligibility: original maturity <1yr, 1-day M floor exposures

References:
    CRR Art. 224: Supervisory haircuts (3 maturity bands)
    CRR Art. 227: Zero volatility adjustments for qualifying repos/SFTs
    CRR Art. 229(1) / PS1/26 Art. 229(1)(b): property value net of prior claims
    CRR Art. 237: Maturity mismatch — eligibility conditions
    CRR Art. 238: Maturity mismatch — adjustment formula (CVAM)
    CRE22.52-53: Basel 3.1 supervisory haircuts (5 maturity bands, higher equity/long-dated)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import ERROR_MATURITY_MISMATCH, crm_warning
from rwa_calc.data.column_spec import ColumnSpec, ensure_columns
from rwa_calc.data.schemas import NON_FINANCIAL_COLLATERAL_TYPES, REAL_ESTATE_COLLATERAL_TYPES
from rwa_calc.domain.enums import CRMCollateralMethod
from rwa_calc.engine.crm.eligibility import (
    credit_linked_note_ineligible_expr,
    debt_security_ineligible_expr,
    equity_ineligible_expr,
    normalise_collateral_type_expr,
)
from rwa_calc.engine.crm.haircut_tables import (
    calculate_adjusted_collateral_value,
    calculate_maturity_mismatch_adjustment,
    lookup_collateral_haircut,
    lookup_fx_haircut,
)
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.compile import decision_table_df, scalar_value
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError
    from rwa_calc.rulebook.resolve import ResolvedRulepack

# CRM regulatory int counts resolved from the common pack once at module load:
# the Art. 227(2)(a) zero-haircut sovereign-CQS cap and the Art. 224(2)
# liquidation periods (feeding the Art. 226(2) sqrt(T_m/10) scaling). All kept
# int end-to-end (Polars ``.le`` / ``pl.lit`` / Python ``<=``), no float
# coercion. (S13-c / S13-h)
_PACK = resolve("crr", date(2026, 1, 1))
_ZERO_HAIRCUT_MAX_SOVEREIGN_CQS = _PACK.int_param("zero_haircut_max_sovereign_cqs").value
_LIQUIDATION_PERIOD_REPO = _PACK.int_param("liquidation_period_repo").value
_LIQUIDATION_PERIOD_SECURED_LENDING = _PACK.int_param("liquidation_period_secured_lending").value

# Optional collateral inputs ``apply_haircuts`` reads. Production collateral
# carries every one (``COLLATERAL_SCHEMA``, plus the exposure lookups' SFT flag);
# a direct caller's hand-built frame may not, and gets each as a typed null that
# takes the same default its absence did.
_HAIRCUT_OPTIONAL_COLUMNS: dict[str, ColumnSpec] = {
    "liquidation_period_days": ColumnSpec(pl.Int32, required=False),
    "exposure_is_sft": ColumnSpec(pl.Boolean, required=False),
    "revaluation_frequency_days": ColumnSpec(pl.Int32, required=False),
    "original_currency": ColumnSpec(pl.String, required=False),
    "maturity_date": ColumnSpec(pl.Date, required=False),
    "residual_maturity_years": ColumnSpec(pl.Float64, required=False),
    # Art. 229(1) claims ranking ahead on a property, as a share of its market
    # value. Absent on the CCR engine's frame (engine/ccr/collateral.py); a null
    # deducts nothing (``prior_claim_amount_expr``).
    "prior_charge_ltv": ColumnSpec(pl.Float64, required=False),
}


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
    - 5-day (repos / SFTs, Art. 224(2)(c)): haircut × 0.7071
    - 10-day (other capital market, Art. 224(2)(b)): no scaling
    - 20-day (secured lending, Art. 224(2)(a)): haircut × 1.4142 [default]

    Liquidation-period default (P1.186):
    - explicit ``liquidation_period_days`` column (non-null) takes precedence
    - else ``exposure_is_sft=True`` → 5 days (Art. 224(2)(c))
    - else → 20 days (Art. 224(2)(a) — secured lending is the regulatory default
      for non-SFT exposures, not the 10-day capital-market period)
    """

    def __init__(self) -> None:
        """Initialize haircut calculator.

        The calculator carries no constructor regime-state: the framework
        (CRR vs Basel 3.1) is read per-call from the effective
        ``CalculationConfig`` (or an explicit ``is_basel_3_1`` argument on the
        single-item methods), so one instance computes correctly under either
        framework. The haircut table is looked up per call via
        ``get_haircut_table(...)``.
        """

    @cites("CRR Art. 224")
    def apply_haircuts(
        self,
        collateral: pl.LazyFrame,
        config: CalculationConfig,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> pl.LazyFrame:
        """
        Apply haircuts to collateral.

        Expects exposure_currency and exposure_maturity columns to already be
        present on collateral (joined via _join_collateral_to_lookups before calling).

        ``value_after_haircut`` is ``max(0, MV x (1 - HC - Hfx) - P)``, where P is a
        property row's prior claims (``prior_claim_amount_expr``, CRR / PS1/26
        Art. 229(1)) and 0 on every other row.

        Args:
            collateral: Collateral data with market values, exposure_currency, exposure_maturity
            config: Calculation configuration

        Returns:
            LazyFrame with haircut-adjusted collateral values
        """
        # Bootstrap: _resolve_pack_for_haircut needs a regime hint only for its
        # no-config fallback; in apply_haircuts config is always present, so the
        # resolved pack's regime matches config. The maturity-band GATE then reads
        # the cited Feature (S9d) — _maturity_band_expression keeps its bool param
        # (Option B). The haircut VALUES already come from the pack DecisionTable.
        resolved_pack = _resolve_pack_for_haircut(pack, config, config.is_basel_3_1)
        is_b31 = resolved_pack.feature("collateral_haircut_maturity_bands_revised")
        haircut_table = decision_table_df(
            resolved_pack.decision("collateral_haircuts"),
            value_name="haircut",
            key_dtypes={"cqs": pl.Int8},
        )

        # The optional inputs this method reads, injected as typed nulls when a
        # direct caller's frame lacks them (production collateral carries every
        # one), so each expression below reads one column instead of branching on
        # its presence. A null takes the same default the absent column did.
        collateral = ensure_columns(collateral, _HAIRCUT_OPTIONAL_COLUMNS)

        # Review CL-02 — the residual maturity both the Art. 224 Table 1 band and
        # the Art. 237-239 mismatch read, derived from the collateral's own
        # maturity_date when residual_maturity_years is not supplied.
        collateral = with_derived_residual_maturity(collateral, config.reporting_date)

        # Add maturity band for bond haircut lookup
        collateral = collateral.with_columns(
            [self._maturity_band_expression(is_b31).alias("maturity_band")]
        )

        # Calculate collateral-specific haircut based on type. The framework is
        # selected by the per-call ``haircut_table`` derived from config above.
        collateral = self._apply_collateral_haircuts(collateral, haircut_table)

        # Scale collateral haircut and FX haircut by liquidation period (Art. 226(2))
        # H_m = H_10 × sqrt(T_m / 10)
        # P1.186: derive default liquidation period from exposure_is_sft when no
        # explicit liquidation_period_days is supplied. Non-SFT secured lending
        # defaults to 20 days (Art. 224(2)(a)), SFT/repo to 5 days (Art. 224(2)(c)).
        sft_default = (
            pl.when(pl.col("exposure_is_sft").fill_null(False))
            .then(pl.lit(_LIQUIDATION_PERIOD_REPO))
            .otherwise(pl.lit(_LIQUIDATION_PERIOD_SECURED_LENDING))
        )
        liq = pl.col("liquidation_period_days").fill_null(sft_default).cast(pl.Float64)
        scaling_factor = (liq / 10.0).sqrt()

        # Art. 226(1): non-daily mark-to-market / non-daily-remargining adjustment.
        # When revaluation_frequency_days (N_R) > 1, scale the haircut upward by
        # sqrt((N_R + T_m - 1) / T_m). Null or N_R <= 1 leaves the multiplier at 1.0.
        # PS1/26 carries Art. 226(1) forward unchanged so the same gate applies under
        # Basel 3.1 — selection is on collateral input, not framework.
        n_r = pl.col("revaluation_frequency_days").fill_null(1).cast(pl.Float64)
        reval_factor = (
            pl.when(n_r > 1.0).then(((n_r + liq - 1.0) / liq).sqrt()).otherwise(pl.lit(1.0))
        )

        # Scale collateral haircut by liquidation period, then apply the Art. 226(1)
        # non-daily-revaluation multiplier (order matters per the spec composition
        # H = H_n × sqrt(T_m/10) × sqrt((N_R + T_m - 1)/T_m)).
        # Non-financial collateral (real_estate, receivables, other_physical) uses
        # Art. 230 / PS1/26 Art. 230(2) HC values which are NOT subject to Art. 226
        # liquidation-period scaling — the Art. 230 HC is a credit-quality multiplier
        # tied to the FCM LGD* formula, not a volatility adjustment. Only the
        # Art. 224 financial-collateral haircuts (cash/gold/bonds/equity) scale.
        is_non_financial_hc = (
            pl.col("collateral_type").str.to_lowercase().is_in(NON_FINANCIAL_COLLATERAL_TYPES)
        )
        scaled_haircut = pl.col("collateral_haircut") * scaling_factor * reval_factor
        collateral = collateral.with_columns(
            pl.when(is_non_financial_hc)
            .then(pl.col("collateral_haircut"))
            .otherwise(scaled_haircut)
            .alias("collateral_haircut")
        )

        # Apply FX haircut (Art. 224 Table 4, scaled per Art. 226).
        # Compare pre-FX-conversion currencies: after `FXConverter.convert_*` has
        # rebased values to the reporting currency, the `currency` column is the
        # reporting currency on both sides and a raw comparison would always be
        # false (P1.135). `original_currency` on collateral and `exposure_currency`
        # (sourced from the exposure's `original_currency` in the processor) both
        # carry the true pre-conversion currency pair.
        #
        # Scope: H_fx is the Art. 224 Table 4 volatility adjustment. Financial
        # collateral takes it in both regimes (CRR Art. 223(1)). Funded
        # NON-financial collateral (real_estate, receivables, other_physical) is
        # the cited pack Feature ``fcm_hfx_applies_to_non_financial`` (review
        # CL-09): CRR Art. 230(1) compares the raw value C with C* / C** and names
        # no currency adjustment (disabled), while PS1/26 Art. 230(1) builds ES
        # "after the application of ... (b) a volatility adjustment for any
        # currency mismatch between the exposure and the collateral (Hfx) in
        # accordance with Articles 224, 226, and 227" for every Foundation
        # Collateral Method type (enabled). Art. 233 H_fx is the separate
        # unfunded-protection twin (engine/crm/guarantees.py).
        #
        # Art. 227: zero-haircut repos waive ALL volatility adjustments including H_fx.
        fx_base = scalar_value(resolved_pack.scalar_param("fx_haircut"))
        hfx_applies_to_type = ~pl.col("collateral_type").is_in(
            NON_FINANCIAL_COLLATERAL_TYPES
        ) | pl.lit(resolved_pack.feature("fcm_hfx_applies_to_non_financial"))
        # Art. 226(1) symmetry: FX haircut is also subject to the non-daily-
        # revaluation scaling — apply ``reval_factor`` after the Art. 226(2)
        # liquidation-period factor, mirroring the collateral haircut path.
        fx_expr = (
            pl.when(pl.col("_is_zero_haircut"))
            .then(pl.lit(0.0))
            .when(collateral_currency_mismatch_expr() & hfx_applies_to_type)
            .then(pl.lit(fx_base) * scaling_factor * reval_factor)
            .otherwise(pl.lit(0.0))
        )
        collateral = collateral.with_columns([fx_expr.alias("fx_haircut")])

        # Calculate adjusted value after haircuts, net of the Art. 229(1) claims that
        # rank ahead on a property (``prior_claim_amount_expr``; 0 on every other row).
        # PS1/26 Art. 229(1)(b) reduces the property value by P / (1 - HC - Hfx), so
        # ES = MV (1 - HC - Hfx) - P, and a negative value is assigned zero. Under CRR
        # the pack's property HC is 0% and Hfx is off for non-financial collateral, so
        # the same expression is Art. 229(1)'s MV - P. Applied before the Art. 237-239
        # maturity adjustment, which scales this value.
        collateral = collateral.with_columns(
            [
                (
                    pl.col("market_value")
                    * (1.0 - pl.col("collateral_haircut") - pl.col("fx_haircut"))
                    - prior_claim_amount_expr()
                )
                .clip(lower_bound=0.0)
                .alias("value_after_haircut"),
            ]
        )

        # Zero out value for ineligible collateral. Three independent gates share the
        # same value/eligibility treatment:
        #   _bond_ineligible          — Art. 197 CQS gate (govt CQS 5-6, corp CQS 4-6,
        #                               securitisation / non-SFT covered bonds); the
        #                               row already carries a 100% collateral_haircut.
        #   _equity_listing_ineligible — Art. 197(1)(f)/198(1)(a) non-main-index /
        #                               non-listed equity (P1.271); the 25%/30%
        #                               supervisory haircut is deliberately left
        #                               intact (valuation ≠ eligibility).
        #   _cln_ineligible           — Art. 218 credit-linked note not attested
        #                               own-issued (P1.274); the 0% cash haircut is
        #                               left intact (valuation ≠ eligibility).
        # ``_apply_collateral_haircuts`` writes all three flags, and the Art. 227
        # ``_is_zero_haircut`` scratch, on every row.
        ineligible_flags = ["_bond_ineligible", "_equity_listing_ineligible", "_cln_ineligible"]
        is_ineligible = pl.any_horizontal([pl.col(f) for f in ineligible_flags])
        cleared = [
            pl.when(is_ineligible)
            .then(pl.lit(0.0))
            .otherwise(pl.col("value_after_haircut"))
            .alias("value_after_haircut")
        ]
        # Also enforce is_eligible_financial_collateral = False for ineligible rows.
        # The flag is NOT injected when absent: a frame without it (a direct
        # caller's) keeps the type-only eligibility ``_apply_collateral_unified``
        # applies to such frames.
        if "is_eligible_financial_collateral" in collateral.collect_schema().names():
            cleared.append(
                pl.when(is_ineligible)
                .then(pl.lit(False))
                .otherwise(pl.col("is_eligible_financial_collateral"))
                .alias("is_eligible_financial_collateral")
            )
        collateral = collateral.with_columns(cleared).drop([*ineligible_flags, "_is_zero_haircut"])

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
                        pl.lit("%; P="),
                        prior_claim_amount_expr().round(0).cast(pl.String),
                        pl.lit("; Adj="),
                        pl.col("value_after_haircut").round(0).cast(pl.String),
                    ]
                ).alias("haircut_calculation"),
            ]
        )

        return collateral

    def apply_exposure_haircut(
        self,
        exposures: pl.LazyFrame,
        is_basel_3_1: bool,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> pl.LazyFrame:
        """
        Add ``exposure_volatility_haircut`` (HE) column per CRR Art. 223(5).

        HE is drawn from the same Art. 224 Table 1 as HC and is non-zero when
        the exposure itself is a debt security — typical for SFTs where the
        firm lends out a bond. Cash exposures and standard loan exposures (no
        ``exposure_collateral_type``) carry HE = 0.

        Liquidation-period scaling (Art. 226(2)) mirrors the collateral-side
        path: ``is_sft=True`` → 5 days (Art. 224(2)(c)), else → 20 days
        (Art. 224(2)(a)). Non-SFT rows carry HE = 0 because Art. 223(5) only
        applies the exposure-side haircut for SFTs lending securities.

        Args:
            exposures: Exposures, optionally carrying exposure-side security cols
            is_basel_3_1: Whether Basel 3.1 maturity bands / haircuts apply

        References:
            CRR Art. 223(5): E* = max(0, E(1 + HE) - CVA(1 - HC - HFX))
            CRR Art. 224 Table 1: supervisory haircuts (10-day base)
            CRR Art. 224(2)(a)/(c): liquidation periods (20d / 5d)
            CRR Art. 226(2): H_m = H_n × sqrt(T_m / 10)
        """
        schema = exposures.collect_schema()
        names = schema.names()

        # When the exposure-side columns are absent (legacy callers), the HE
        # column collapses to 0.0 — preserves prior behaviour.
        if "exposure_collateral_type" not in names:
            return exposures.with_columns(pl.lit(0.0).alias("exposure_volatility_haircut"))

        is_b31 = is_basel_3_1
        resolved_pack = _resolve_pack_for_haircut(pack, None, is_b31)
        ct = pl.col("exposure_collateral_type").str.to_lowercase()

        # Map exposure security type to the canonical haircut-table key. Cash
        # collapses to HE = 0, equity / non-bond rows fall through to "other".
        # We only model bond securities here — other types are exotic on the
        # exposure side and HE remains 0 conservatively.
        norm_type = (
            pl.when(ct.is_in(["govt_bond", "sovereign_bond", "government_bond", "gilt"]))
            .then(pl.lit("govt_bond"))
            .when(ct.is_in(["corp_bond", "corporate_bond"]))
            .then(pl.lit("corp_bond"))
            .otherwise(pl.lit(None, dtype=pl.String))
        )

        # Reuse the collateral maturity-band classifier but key off the
        # exposure-side residual-maturity column.
        if "exposure_security_residual_maturity_years" in names:
            mat = pl.col("exposure_security_residual_maturity_years")
        else:
            mat = pl.lit(None, dtype=pl.Float64)
        if is_b31:
            band = (
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
        else:
            band = (
                pl.when(mat.is_null())
                .then(pl.lit("5y_plus"))
                .when(mat <= 1.0)
                .then(pl.lit("0_1y"))
                .when(mat <= 5.0)
                .then(pl.lit("1_5y"))
                .otherwise(pl.lit("5y_plus"))
            )

        if "exposure_security_cqs" in names:
            cqs_expr = pl.col("exposure_security_cqs").cast(pl.Int8).fill_null(-1)
        else:
            cqs_expr = pl.lit(-1).cast(pl.Int8)

        exposures = exposures.with_columns(
            [
                norm_type.alias("_he_lookup_type"),
                cqs_expr.alias("_he_lookup_cqs"),
                band.alias("_he_lookup_maturity_band"),
            ]
        )

        # Reuse the haircut table; only bond rows (cqs IS NOT NULL) are joined
        # on. Equity / cash / null types miss the join → haircut becomes null
        # → HE = 0.
        ht = (
            decision_table_df(
                resolved_pack.decision("collateral_haircuts"),
                value_name="haircut",
                key_dtypes={"cqs": pl.Int8},
            )
            .lazy()
            .filter(pl.col("collateral_type").is_in(["govt_bond", "corp_bond"]))
            .select(
                pl.col("collateral_type").alias("_he_lookup_type"),
                pl.col("cqs").cast(pl.Int8).alias("_he_lookup_cqs"),
                pl.col("maturity_band").alias("_he_lookup_maturity_band"),
                pl.col("haircut").alias("_he_haircut"),
            )
        )

        exposures = exposures.join(
            ht,
            on=["_he_lookup_type", "_he_lookup_cqs", "_he_lookup_maturity_band"],
            how="left",
        )

        # Liquidation-period scaling: Art. 226(2). is_sft=True → 5d; else 20d.
        sft_flag = pl.col("is_sft").fill_null(False) if "is_sft" in names else pl.lit(False)
        liq = (
            pl.when(sft_flag)
            .then(pl.lit(float(_LIQUIDATION_PERIOD_REPO)))
            .otherwise(pl.lit(float(_LIQUIDATION_PERIOD_SECURED_LENDING)))
        )
        scaling_factor = (liq / 10.0).sqrt()

        # HE only applies on the SFT path (Art. 223(5) — exposures lending out
        # debt securities). Non-SFT rows force HE = 0 even if a bond was tagged.
        he_expr = (
            pl.when(sft_flag & pl.col("_he_haircut").is_not_null())
            .then(pl.col("_he_haircut") * scaling_factor)
            .otherwise(pl.lit(0.0))
        )

        return exposures.with_columns(he_expr.alias("exposure_volatility_haircut")).drop(
            ["_he_lookup_type", "_he_lookup_cqs", "_he_lookup_maturity_band", "_he_haircut"]
        )

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
        haircut_table: pl.DataFrame,
    ) -> pl.LazyFrame:
        """Apply collateral-type-specific haircuts via lookup table join.

        Art. 227 zero-haircut: when ``qualifies_for_zero_haircut`` is True and the
        collateral type is eligible (cash/deposit or CQS ≤ 1 sovereign bond), both
        H_c and H_fx are set to 0%.  The ``_is_zero_haircut`` flag is propagated so
        ``apply_haircuts`` can also zero the FX haircut.

        Args:
            collateral: Collateral data with normalised lookup keys
            haircut_table: Framework-specific haircut table (CRR or Basel 3.1)
        """
        # Ensure issuer_type + Art. 197(1)(h) securitisation-eligibility columns
        # exist for bond-type normalization / the securitisation gate below.
        collateral = ensure_columns(
            collateral,
            {
                "issuer_type": ColumnSpec(pl.String, required=False),
                "is_resecuritisation": ColumnSpec(pl.Boolean, default=False, required=False),
                "securitisation_position_risk_weight": ColumnSpec(pl.Float64, required=False),
            },
        )
        schema = collateral.collect_schema()

        # Art. 227: determine whether zero-haircut flag column is available
        has_zero_haircut_col = "qualifies_for_zero_haircut" in schema.names()
        # Art. 224 Table 3/4: is_main_index distinguishes main-index vs other-listed equity
        has_main_index_col = "is_main_index" in schema.names()

        # Normalize collateral type and build sentinel join keys. Securitisation
        # positions look up by (cqs, maturity_band) exactly like bonds (Art. 224
        # Table 1 securitisation column).
        bond_types = pl.col("_lookup_type").is_in(["govt_bond", "corp_bond", "securitisation"])
        is_equity = pl.col("_lookup_type") == "equity"

        # Equity main-index lookup: prefer is_main_index when available,
        # fall back to is_eligible_financial_collateral for backward compatibility.
        # P1.237/P1.271 — CRR/PS1-26 Art. 197(1)(f)/198(1)(a): only main-index
        # equities take the cheaper 15%/20% haircut and are eligible under all
        # methods; other-listed equities take 25%/30% (and are repo-only). A null
        # is_main_index is UNKNOWN index membership and must default to
        # other-listed (False), never to the cheaper main-index treatment — the
        # project's never-fill-anti-conservative rule.
        if has_main_index_col:
            _equity_main_index_expr = pl.col("is_main_index").fill_null(False).cast(pl.Int8)
        else:
            _equity_main_index_expr = (
                pl.col("is_eligible_financial_collateral").fill_null(False).cast(pl.Int8)
            )

        collateral = collateral.with_columns(
            [normalise_collateral_type_expr().alias("_lookup_type")]
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
        ht = haircut_table.lazy().with_columns(
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

        # Debt-security eligibility per CRR Art. 197(1)(b)/(d)/(h) and Art. 207(2)
        # (CQS gate, covered bonds outside a repo, resecuritisation / >100%-RW
        # securitisation positions). The predicate lives in engine/crm/eligibility.py
        # so the Art. 222 Simple Method reads the SAME definition — Art. 197 binds
        # "under all approaches and methods". A gated row is routed through the
        # _bond_ineligible machinery below, which zeros value_after_haircut and
        # overrides is_eligible_financial_collateral.
        _ineligible_bond = debt_security_ineligible_expr(schema.names())

        # Art. 227(2)(a): eligible for zero haircut if cash/deposit or CQS ≤ 1 sovereign bond
        _zero_type_eligible = pl.col("_lookup_type").is_in(["cash"]) | (
            (pl.col("_lookup_type") == "govt_bond")
            & pl.col("issuer_cqs").fill_null(99).le(_ZERO_HAIRCUT_MAX_SOVEREIGN_CQS)
        )

        if has_zero_haircut_col:
            _is_art227 = pl.col("qualifies_for_zero_haircut").fill_null(False) & _zero_type_eligible
        else:
            _is_art227 = pl.lit(False)

        # Art. 232: life insurance uses surrender value directly — no supervisory haircut
        _is_life_insurance = pl.col("_lookup_type") == "life_insurance"

        # P1.271 — CRR/PS1-26 Art. 197(1)(f)/198(1)(a): non-main-index equity is
        # eligible collateral only if listed on a recognised exchange. This is an
        # ELIGIBILITY gate, distinct from the 25%/30% other-listed supervisory
        # haircut (a valuation parameter, left intact above): apply_haircuts zeros
        # value_after_haircut and clears is_eligible_financial_collateral for a
        # gated row, but its collateral_haircut keeps the looked-up band value.
        _equity_listing_ineligible = equity_ineligible_expr(
            schema.names(), method=CRMCollateralMethod.COMPREHENSIVE
        )

        # P1.274 — CRR/PS1-26 Art. 218: a credit-linked note is cash collateral
        # only when issued by the lending institution itself. A CLN not attested
        # own-issued is ineligible funded protection (a third-party CLN carries
        # Art. 194(4) wrong-way risk to its reference entity). Same ELIGIBILITY
        # gate as equity: apply_haircuts zeros value_after_haircut and clears
        # is_eligible_financial_collateral; the 0% cash collateral_haircut the row
        # would otherwise take is irrelevant once the value is zeroed.
        _cln_ineligible = credit_linked_note_ineligible_expr(schema.names())

        # Assign haircut: life insurance 0% → Art. 227 zero → ineligible bond 100% → lookup → 40%
        collateral = collateral.with_columns(
            [
                _ineligible_bond.alias("_bond_ineligible"),
                _equity_listing_ineligible.alias("_equity_listing_ineligible"),
                _cln_ineligible.alias("_cln_ineligible"),
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

    @cites("CRR Art. 237")
    @cites("CRR Art. 238")
    def apply_maturity_mismatch(
        self,
        collateral: pl.LazyFrame,
        config: CalculationConfig,
        *,
        errors: list[CalculationError] | None = None,
    ) -> pl.LazyFrame:
        """
        Apply maturity mismatch adjustment per CRR Art. 237-238.

        A mismatch exists only where the protection's residual maturity is LESS
        THAN the exposure's (Art. 237(1)); the comparison is made on the RAW
        residuals. Equal residuals — an interbank loan against an interbank
        deposit sharing one maturity date, however short — are not a mismatch and
        keep full protection. The exposure residual ``T`` is capped at five years
        (Art. 238(1)) and is NOT floored: the 0.25 term belongs to the scaling
        formula below, which is reached only when ``t >= 0.25`` and ``t < T``, so
        its denominator is always positive. Flooring ``T`` before the comparison
        fabricated a mismatch for every matched pair maturing within three months
        of the reporting date and zeroed its protection (escape log 2026-09-05;
        the guarantee twin in ``engine/crm/guarantees.py`` already compares raw
        residuals).

        Art. 237 ineligibility conditions (protection zeroed when a mismatch exists):
        - 237(1): protection residual maturity < 3 months
        - 237(2)(a): original maturity of protection < 1 year
        - 237(2)(b) with Art. 162(3): exposures subject to the one-day IRB
          maturity floor — ANY mismatch makes protection ineligible (repos/SFTs
          with daily margining)

        Formula (Art. 238): CVAM = CVA × (t - 0.25) / (T - 0.25)
        where t = collateral residual maturity, T = min(exposure residual maturity, 5).

        Args:
            collateral: Collateral with value_after_haircut, residual_maturity_years,
                and exposure_maturity (Date) columns. Optionally:
                original_maturity_years (Float64) and
                exposure_has_one_day_maturity_floor (Boolean).
            config: Calculation configuration (provides reporting_date)
            errors: CRM error channel. When supplied, ONE rolled-up CRM002
                warning records how many rows the gates zeroed and how many the
                formula scaled (``_record_maturity_mismatch_adjustments``);
                direct unit-test callers may omit it.

        Returns:
            LazyFrame with maturity-adjusted collateral values
        """
        reporting_date = config.reporting_date
        coll_schema = collateral.collect_schema()

        # Exposure residual maturity T in years: Art. 238(1) caps it at five years
        # and does not floor it. A null exposure maturity defaults to 5y — the
        # most conservative recognised maturity, mirroring the guarantee twin.
        exposure_maturity_years_expr = (
            residual_years_expr("exposure_maturity", reporting_date)
            .clip(upper_bound=5.0)
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

        # Art. 237(1): a mismatch exists only where the protection residual is
        # strictly LESS than the exposure residual — compared raw, no floor on
        # either side. Every gate and the scaling below are conditioned on it.
        has_mismatch = pl.col("coll_maturity") < pl.col("_exposure_maturity_years")

        # Calculate maturity mismatch adjustment per Art. 237-238
        collateral = collateral.with_columns(
            [
                # No adjustment when collateral maturity >= exposure maturity
                pl.when(~has_mismatch)
                .then(pl.lit(1.0))
                # Art. 237(1): no protection when the (shorter) collateral residual
                # is under three months
                .when(pl.col("coll_maturity") < 0.25)
                .then(pl.lit(0.0))
                # Art. 237(2)(a): original maturity of protection < 1 year → ineligible
                .when(pl.col("_orig_maturity") < 1.0)
                .then(pl.lit(0.0))
                # Art. 162(3)/237(2)(b): 1-day M floor exposure → any mismatch makes
                # protection ineligible (repos/SFTs with daily margining)
                .when(pl.col("_has_1d_floor"))
                .then(pl.lit(0.0))
                # CVAM = (t - 0.25) / (T - 0.25), T capped at 5y. Reached only with
                # t >= 0.25 and t < T, so T - 0.25 > 0 without any floor on T.
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

        # CRR/PS1-26 Art. 237-239: say what was taken away. Until the 2026-09-05
        # escape CRM002 was declared and never produced, so a netted deposit
        # zeroed by the gates left no record beside the unsecured LGD.
        if errors is not None:
            _record_maturity_mismatch_adjustments(collateral, errors)

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
        is_basel_3_1: bool = False,
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
            is_basel_3_1: Whether Basel 3.1 haircut tables apply (default CRR)

        Returns:
            HaircutResult with all haircut details
        """
        # Art. 227: zero-haircut for qualifying repos — check type eligibility
        if qualifies_for_zero_haircut and _is_art227_eligible(collateral_type, cqs):
            return self._build_art227_zero_result(
                collateral_type=collateral_type,
                market_value=market_value,
                collateral_maturity_years=collateral_maturity_years,
                exposure_maturity_years=exposure_maturity_years,
                original_maturity_years=original_maturity_years,
                has_one_day_maturity_floor=has_one_day_maturity_floor,
            )

        # Art. 232: Life insurance — no supervisory haircut (surrender value IS the value)
        if collateral_type.lower() == "life_insurance":
            return self._build_life_insurance_result(
                market_value=market_value,
                collateral_currency=collateral_currency,
                exposure_currency=exposure_currency,
                liquidation_period_days=liquidation_period_days,
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
            is_basel_3_1=is_basel_3_1,
            liquidation_period_days=liquidation_period_days,
        )

        # Ineligible bonds: zero adjusted value
        if coll_haircut is None:
            return _build_ineligible_result(
                market_value=market_value, collateral_type=collateral_type, cqs=cqs
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
        adjusted, maturity_adj = _apply_optional_maturity_mismatch(
            adjusted=adjusted,
            collateral_maturity_years=collateral_maturity_years,
            exposure_maturity_years=exposure_maturity_years,
            original_maturity_years=original_maturity_years,
            has_one_day_maturity_floor=has_one_day_maturity_floor,
            denominator=market_value * (1 - coll_haircut - fx_haircut),
        )

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

    @staticmethod
    def _build_art227_zero_result(
        *,
        collateral_type: str,
        market_value: Decimal,
        collateral_maturity_years: float | None,
        exposure_maturity_years: float | None,
        original_maturity_years: float | None,
        has_one_day_maturity_floor: bool,
    ) -> HaircutResult:
        """Art. 227: All volatility adjustments zeroed (H_c = H_e = H_fx = 0%).

        Maturity mismatch is still applied via Art. 237-238 if applicable.
        """
        adjusted, maturity_adj = _apply_optional_maturity_mismatch(
            adjusted=market_value,
            collateral_maturity_years=collateral_maturity_years,
            exposure_maturity_years=exposure_maturity_years,
            original_maturity_years=original_maturity_years,
            has_one_day_maturity_floor=has_one_day_maturity_floor,
            denominator=market_value,
        )
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

    @staticmethod
    def _build_life_insurance_result(
        *,
        market_value: Decimal,
        collateral_currency: str,
        exposure_currency: str,
        liquidation_period_days: int,
    ) -> HaircutResult:
        """Art. 232: Life insurance — surrender value IS the value (no supervisory haircut)."""
        fx_h = lookup_fx_haircut(exposure_currency, collateral_currency, liquidation_period_days)
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


def create_haircut_calculator() -> HaircutCalculator:
    """
    Create a haircut calculator instance.

    The calculator carries no constructor regime-state — the framework is read
    per-call from the effective config (or an explicit ``is_basel_3_1`` argument
    on the single-item methods).

    Returns:
        HaircutCalculator ready for use
    """
    return HaircutCalculator()


@cites("CRR Art. 238")
@cites("PS1/26 Art. 238")
def with_derived_residual_maturity(collateral: pl.LazyFrame, reporting_date: date) -> pl.LazyFrame:
    """Fill a null collateral ``residual_maturity_years`` from its ``maturity_date``.

    CRR Art. 238(1) and PS1/26 Art. 238(1) take "the maturity of the credit
    protection to be the time to the earliest date at which the protection may
    terminate or be terminated", and PS1/26 Art. 237(1) finds a maturity
    mismatch "when the residual maturity of the credit protection is less than
    that of the protected exposure". A pledge supplied with only its
    ``maturity_date`` states that date; before review CL-02 nothing read it, so
    the null residual took the mismatch step's 10-year default and a one-year
    deposit protected a five-year loan in full. A supplied residual wins; the
    date is used only where the residual is null, and a row with neither stays
    null (the downstream defaults are unchanged). The residual counts days
    /365.25 from the reporting date — the basis ``apply_maturity_mismatch``
    measures the EXPOSURE residual on, so a pledge and a loan sharing one
    maturity date compare equal (no phantom mismatch). The same residual feeds
    the Art. 224 Table 1 maturity band, which Table 1 also keys on "residual
    maturity". Expects both columns present (``apply_haircuts`` injects them).
    """
    return collateral.with_columns(
        pl.coalesce(
            pl.col("residual_maturity_years"), residual_years_expr("maturity_date", reporting_date)
        ).alias("residual_maturity_years")
    )


def residual_years_expr(date_col: str, reporting_date: date) -> pl.Expr:
    """Years from ``reporting_date`` to the date in ``date_col`` (days / 365.25).

    The one day-count the collateral maturity-mismatch step uses for BOTH sides,
    the exposure residual T and the protection residual t, so equal dates give
    t == T exactly. Null where the date is null; negative once the date has
    passed.
    """
    return (pl.col(date_col).cast(pl.Date) - pl.lit(reporting_date)).dt.total_days().cast(
        pl.Float64
    ) / 365.25


@cites("CRR Art. 224")
@cites("PS1/26 Art. 230")
def collateral_currency_mismatch_expr() -> pl.Expr:
    """True where the collateral cannot be shown to share the exposure's currency.

    Compares pre-FX-conversion denominations: after ``FXConverter`` has rebased
    values, ``currency`` is the reporting currency on both sides, so the
    collateral's denomination is ``original_currency``, falling back per row to
    ``currency`` (frames are diagonal-concatenated — user collateral plus the
    synthetic netting rows — so a row can lack the audit value while the column
    exists; escape log 2026-11-13). ``exposure_currency`` is the exposure's own
    denomination from the processor's lookups.

    A NULL collateral denomination is a mismatch (review CL-14): CRR Art. 223(2)
    and PS1/26 Art. 230(1)(b) apply H_fx for "any currency mismatch between the
    exposure and the collateral", and an unknown denomination cannot establish
    that there is none. ``null != x`` is null, which switched H_fx off silently;
    the null test makes it the conservative True. A null EXPOSURE currency with a
    known collateral one stays null (no H_fx), as before.
    """
    denomination = collateral_denomination_expr()
    return denomination.is_null() | (denomination != pl.col("exposure_currency"))


def collateral_denomination_expr() -> pl.Expr:
    """The collateral's own currency: ``original_currency`` (pre-FX-conversion),
    else ``currency`` per row. Null when the row states neither."""
    return pl.coalesce("original_currency", "currency")


@cites("CRR Art. 229")
@cites("PS1/26 Art. 229")
def prior_claim_amount_expr() -> pl.Expr:
    """P — the claims ranking ahead of the institution's on a property, in money.

    ``prior_charge_ltv`` x ``market_value`` (the input is a share of the property
    value, as the SA Art. 124C(3) LTV reads it) on a real-estate row; 0 on every
    other row, on a null ``prior_charge_ltv`` (no prior claim reported) and when a
    caller's frame carries no such column (``_HAIRCUT_OPTIONAL_COLUMNS`` injects a
    typed null). A negative input — outside the column's domain, which the input
    gate reports — deducts nothing rather than adding value.

    A real-estate row is any case-insensitive ``REAL_ESTATE_COLLATERAL_TYPES``
    spelling: the set ``collateral_category_expr`` files under the real-estate
    category, which carries the row into ``collateral_re_value``,
    ``crm_alloc_real_estate`` and the C* test. It is deliberately not the literal
    ``"real_estate"`` that the SA LTV derivation (``engine/hierarchy/re_ltv.py``)
    reads, which would leave a ``"CRE"`` pledge in that pool at its full value. On a
    row valued by ``pledge_percentage`` alone, ``market_value`` is the pledged amount
    the CRM processor resolves (``pledge_percentage`` x the beneficiary's EAD), so P
    is read against that; the SA LTV derivation has no counterpart, as it ignores a
    property without a ``market_value``.

    ``apply_haircuts`` subtracts it from the haircut value: CRR Art. 229(1) values
    the property net of "any prior claims", and PS1/26 Art. 229(1)(b) reduces it by
    P / (1 - HC - Hfx), "P = total value of all claims ranking higher than the
    institution's claim", which nets to MV (1 - HC - Hfx) - P on the ES.

    The whole of ``prior_charge_ltv`` is taken as P. The input covers prior AND
    pari-passu claims (Art. 124C(3)) in one figure, so the PS1/26 Art. 229(1)(c)
    pari-passu limb — keep the institution's proportion of what remains — is not
    applied. Deducting a pari-passu claim Q in full never recognises more than that
    limb (for a loan; an exposure-side haircut HE is not considered): with R the
    haircut value and E the institution's claim, R - Q is at most R x E / (E + Q)
    whenever R <= E + Q, and above that both exceed E, the most ES can be. CRR
    Art. 229(1) names prior claims only, so there the deduction of a pari-passu claim
    is conservative outright. Both hold until the input is split into prior,
    pari-passu and own-share amounts (P1.449).
    """
    is_property = pl.col("collateral_type").str.to_lowercase().is_in(REAL_ESTATE_COLLATERAL_TYPES)
    return (
        pl.when(is_property & pl.col("prior_charge_ltv").is_not_null())
        .then(pl.col("prior_charge_ltv").clip(lower_bound=0.0) * pl.col("market_value"))
        .otherwise(pl.lit(0.0))
    )


def _resolve_pack_for_haircut(
    pack: ResolvedRulepack | None,
    config: CalculationConfig | None,
    is_basel_3_1: bool,
) -> ResolvedRulepack:
    """Resolve a rulepack for the (date-independent) supervisory-haircut lookup.

    Production threads ``pack`` from the CRM stage; the ``config`` fallback
    (``apply_haircuts``) and the ``is_basel_3_1`` placeholder-date fallback
    (``apply_exposure_haircut``, which has no config) keep the direct unit-test
    callers working without re-plumbing. The Art. 224 haircut table carries no
    ``Schedule``, so the placeholder reporting date is immaterial to the lookup.
    """
    if pack is not None:
        return pack
    if config is not None:
        return RulepackV0.from_config(config).pack
    return resolve("b31" if is_basel_3_1 else "crr", date(2026, 1, 1))


def _is_art227_eligible(collateral_type: str, cqs: int | None) -> bool:
    """Art. 227(2)(a) eligibility: cash/deposit or CQS ≤ 1 sovereign bond."""
    norm = collateral_type.lower()
    if norm in ("cash", "deposit"):
        return True
    is_sovereign = norm in ("govt_bond", "sovereign_bond", "government_bond", "gilt")
    return is_sovereign and cqs is not None and cqs <= _ZERO_HAIRCUT_MAX_SOVEREIGN_CQS


def _build_ineligible_result(
    *, market_value: Decimal, collateral_type: str, cqs: int | None
) -> HaircutResult:
    """Art. 197 ineligible bond: zero adjusted value, descriptive trail."""
    return HaircutResult(
        original_value=market_value,
        collateral_haircut=Decimal("1.0"),
        fx_haircut=Decimal("0.0"),
        maturity_adjustment=Decimal("0.0"),
        adjusted_value=Decimal("0"),
        description=(
            f"MV={market_value:,.0f}; INELIGIBLE per Art. 197 (type={collateral_type}, CQS={cqs})"
        ),
    )


def _apply_optional_maturity_mismatch(
    *,
    adjusted: Decimal,
    collateral_maturity_years: float | None,
    exposure_maturity_years: float | None,
    original_maturity_years: float | None,
    has_one_day_maturity_floor: bool,
    denominator: Decimal,
) -> tuple[Decimal, Decimal]:
    """Apply Art. 237-238 maturity mismatch if both maturities are present.

    Returns the (possibly adjusted) value and the implied maturity-adjustment ratio.
    ``denominator`` is the pre-mismatch value used to derive the ratio (i.e. the
    Art. 223(5) E*-equivalent for the haircut path, or ``market_value`` for the
    Art. 227 zero-haircut path).
    """
    maturity_adj = Decimal("1.0")
    if not (collateral_maturity_years and exposure_maturity_years):
        return adjusted, maturity_adj
    adjusted, _ = calculate_maturity_mismatch_adjustment(
        collateral_value=adjusted,
        collateral_maturity_years=collateral_maturity_years,
        exposure_maturity_years=exposure_maturity_years,
        original_maturity_years=original_maturity_years,
        has_one_day_maturity_floor=has_one_day_maturity_floor,
    )
    if adjusted > Decimal("0") and denominator > Decimal("0"):
        maturity_adj = adjusted / denominator
    return adjusted, maturity_adj


def _record_maturity_mismatch_adjustments(
    collateral: pl.LazyFrame,
    errors: list[CalculationError],
) -> None:
    """Append ONE rolled-up CRM002 warning counting the collateral rows the
    CRR/PS1-26 Art. 237-239 maturity treatment zeroed or scaled.

    Called from ``HaircutCalculator.apply_maturity_mismatch`` on the frame it has
    just annotated, so ``value_after_haircut`` and ``maturity_adjustment_factor``
    are present by construction. Rows that carried no value before the step are
    not counted — zeroing nothing is not a loss — and a null value or factor
    drops out of the count. Rolled up to a per-run count (the CRM018 idiom) so
    an interbank book cannot flood the error channel.
    """
    factor = pl.col("maturity_adjustment_factor")
    had_value = pl.col("value_after_haircut") > 0.0
    counts = collateral.select(
        (had_value & (factor <= 0.0)).cast(pl.UInt32).sum().alias("zeroed"),
        (had_value & (factor > 0.0) & (factor < 1.0)).cast(pl.UInt32).sum().alias("scaled"),
    ).collect()
    zeroed = int(counts["zeroed"][0] or 0)
    scaled = int(counts["scaled"][0] or 0)
    if zeroed <= 0 and scaled <= 0:
        return
    errors.append(
        crm_warning(
            ERROR_MATURITY_MISMATCH,
            f"{zeroed} collateral row(s) lost all protection to the Art. 237 "
            f"maturity gates (protection residual under three months and shorter "
            f"than the exposure; original term under one year with a mismatch; or "
            f"a one-day-maturity-floor exposure with a mismatch) and {scaled} row(s) "
            f"were scaled by the Art. 238 factor (t - 0.25) / (T - 0.25). Netted "
            f"deposits (CRR Art. 219) appear here as NETTING_ cash rows.",
            regulatory_reference="CRR/PS1-26 Art. 237-239",
        )
    )
