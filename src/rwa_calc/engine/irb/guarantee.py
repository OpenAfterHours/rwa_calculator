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
- CRR Art. 153(3), 202-203: Double default treatment
- CRR Art. 161(3): Guarantor PD substitution for expected loss
- CRR Art. 213, 215-217: Guarantee eligibility and substitution
- Basel 3.1 CRE22.70-85: Parameter substitution approach
- CRR Art. 306, CRE54.14-15: CCP risk weights
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.data.tables.crr_risk_weights import QCCP_CLIENT_CLEARED_RW, QCCP_PROPRIETARY_RW
from rwa_calc.data.tables.eu_sovereign import build_eu_domestic_currency_expr
from rwa_calc.engine.irb.formulas import (
    _double_default_multiplier_expr,
    _parametric_irb_risk_weight_expr,
    _pd_floor_expression,
)

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


def apply_guarantee_substitution(lf: pl.LazyFrame, config: CalculationConfig) -> pl.LazyFrame:
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
       corporate underlying, and eligible guarantor with internal PD. Provides
       lower capital charge than substitution for high-quality guarantors.

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

    # Check if guarantee columns exist
    if "guaranteed_portion" not in cols or "guarantor_entity_type" not in cols:
        return lf

    has_expected_loss = "expected_loss" in cols
    has_guarantor_pd = "guarantor_pd" in cols
    use_parameter_substitution = config.is_basel_3_1 and has_guarantor_pd

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

    # --- Compute SA risk weight for guarantor (used for SA guarantors) ---
    lf = _compute_guarantor_rw_sa(lf, cols, config)

    # --- Basel 3.1 parameter substitution for IRB guarantors (CRE22.70-85) ---
    lf = _apply_parameter_substitution(lf, cols, config, use_parameter_substitution)

    # --- Double default treatment (CRR Art. 153(3), 202-203) ---
    lf = _apply_double_default(lf, cols, config, has_guarantor_pd, use_parameter_substitution)

    # --- Blend RWA and adjust expected loss ---
    ead_col = "ead_final" if "ead_final" in cols else "ead"

    # Check if guarantee is beneficial (guarantor RW < borrower IRB RW)
    # Non-beneficial guarantees should NOT be applied per CRR Art. 213
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

    # Calculate blended RWA using substitution approach
    lf = lf.with_columns(
        [
            pl.when(
                (pl.col("guaranteed_portion").fill_null(0) > 0)
                & (pl.col("guarantor_rw").is_not_null())
                & (pl.col("is_guarantee_beneficial"))
            )
            .then(
                pl.col("rwa_irb_original")
                * (pl.col("unguaranteed_portion") / pl.col(ead_col)).fill_null(1.0)
                + pl.col("guaranteed_portion") * pl.col("guarantor_rw")
            )
            .otherwise(pl.col("rwa_irb_original"))
            .alias("rwa"),
        ]
    )

    # Calculate blended risk weight for reporting
    lf = lf.with_columns(
        [
            (pl.col("rwa") / pl.col(ead_col)).fill_null(0.0).alias("risk_weight"),
        ]
    )

    # Adjust expected loss for guaranteed portion
    if has_expected_loss:
        lf = _adjust_expected_loss(lf, config, ead_col, use_parameter_substitution)

    # Track guarantee status and method for reporting
    lf = _add_guarantee_status_columns(lf)

    # Drop internal tracking columns
    lf = lf.drop("_is_pd_substitution", "_is_dd_applied", "guarantor_rw_sa")

    return lf


# =============================================================================
# PRIVATE HELPERS
# =============================================================================


def _compute_guarantor_rw_sa(
    lf: pl.LazyFrame,
    cols: list[str],
    config: CalculationConfig,
) -> pl.LazyFrame:
    """Compute SA risk weight for guarantor based on entity type and CQS."""
    use_uk_deviation = config.base_currency == "GBP"

    # Ensure guarantor_exposure_class is available (set by CRM processor;
    # fallback for unit tests that construct LazyFrames directly)
    if "guarantor_exposure_class" not in cols:
        from rwa_calc.engine.classifier import ENTITY_TYPE_TO_SA_CLASS

        lf = lf.with_columns(
            pl.col("guarantor_entity_type")
            .fill_null("")
            .replace_strict(ENTITY_TYPE_TO_SA_CLASS, default="")
            .alias("guarantor_exposure_class"),
        )
    if "guarantor_is_ccp_client_cleared" not in cols:
        lf = lf.with_columns(
            pl.lit(None).cast(pl.Boolean).alias("guarantor_is_ccp_client_cleared"),
        )

    _gec = pl.col("guarantor_exposure_class").fill_null("")

    # Art. 114(3)/(4): Domestic CGCB guarantors -> 0% RW regardless of CQS
    _has_country = "guarantor_country_code" in lf.collect_schema().names()
    _is_uk_domestic_guarantor = (
        (pl.col("guarantor_country_code").fill_null("") == "GB") & (pl.col("currency") == "GBP")
        if _has_country
        else pl.lit(False)
    )
    _is_eu_domestic_guarantor = (
        build_eu_domestic_currency_expr("guarantor_country_code", "currency")
        if _has_country
        else pl.lit(False)
    )
    _is_domestic_guarantor = _is_uk_domestic_guarantor | _is_eu_domestic_guarantor

    return lf.with_columns(
        [
            pl.when(pl.col("guaranteed_portion").fill_null(0) <= 0)
            .then(pl.lit(None).cast(pl.Float64))
            # Art. 114(3)/(4): Domestic sovereign -> 0% regardless of CQS
            .when((_gec == "central_govt_central_bank") & _is_domestic_guarantor)
            .then(pl.lit(0.0))
            # CGCB guarantors (sovereign, central_bank)
            .when(_gec == "central_govt_central_bank")
            .then(
                pl.when(pl.col("guarantor_cqs") == 1)
                .then(pl.lit(0.0))
                .when(pl.col("guarantor_cqs") == 2)
                .then(pl.lit(0.20))
                .when(pl.col("guarantor_cqs") == 3)
                .then(pl.lit(0.50))
                .when(pl.col("guarantor_cqs").is_in([4, 5]))
                .then(pl.lit(1.0))
                .when(pl.col("guarantor_cqs") == 6)
                .then(pl.lit(1.50))
                .otherwise(pl.lit(1.0))
            )
            # CCP guarantors: 2% proprietary / 4% client-cleared
            # (CRR Art. 306, CRE54.14-15) -- overrides institution CQS weights
            .when(pl.col("guarantor_entity_type") == "ccp")
            .then(
                pl.when(pl.col("guarantor_is_ccp_client_cleared").fill_null(False))
                .then(pl.lit(float(QCCP_CLIENT_CLEARED_RW)))
                .otherwise(pl.lit(float(QCCP_PROPRIETARY_RW)))
            )
            # Institution/MDB guarantors (institution, bank, mdb, etc.)
            .when(_gec.is_in(["institution", "mdb"]))
            .then(
                pl.when(pl.col("guarantor_cqs") == 1)
                .then(pl.lit(0.20))
                .when(pl.col("guarantor_cqs") == 2)
                .then(pl.lit(0.30) if use_uk_deviation else pl.lit(0.50))
                .when(pl.col("guarantor_cqs") == 3)
                .then(pl.lit(0.50))
                .when(pl.col("guarantor_cqs").is_in([4, 5]))
                .then(pl.lit(1.0))
                .when(pl.col("guarantor_cqs") == 6)
                .then(pl.lit(1.50))
                .otherwise(pl.lit(0.40))
            )
            # Corporate guarantors (corporate, company)
            .when(_gec.is_in(["corporate", "corporate_sme"]))
            .then(
                pl.when(pl.col("guarantor_cqs") == 1)
                .then(pl.lit(0.20))
                .when(pl.col("guarantor_cqs") == 2)
                .then(pl.lit(0.50))
                .when(pl.col("guarantor_cqs").is_in([3, 4]))
                .then(pl.lit(1.0))
                .when(pl.col("guarantor_cqs").is_in([5, 6]))
                .then(pl.lit(1.50))
                .otherwise(pl.lit(1.0))
            )
            .otherwise(pl.lit(None).cast(pl.Float64))
            .alias("guarantor_rw_sa"),
        ]
    )


def _apply_parameter_substitution(
    lf: pl.LazyFrame,
    cols: list[str],
    config: CalculationConfig,
    use_parameter_substitution: bool,
) -> pl.LazyFrame:
    """Apply Basel 3.1 parameter substitution for IRB guarantors (CRE22.70-85)."""
    if use_parameter_substitution:
        from rwa_calc.data.tables.crr_firb_lgd import get_firb_lgd_table_for_framework

        firb_lgd_table = get_firb_lgd_table_for_framework(is_basel_3_1=True)
        firb_lgd_senior = float(firb_lgd_table["unsecured_senior"])  # 0.40

        # Ensure columns required by _parametric_irb_risk_weight_expr exist
        ensure_cols: list[pl.Expr] = []
        if "turnover_m" not in cols:
            ensure_cols.append(pl.lit(None).cast(pl.Float64).alias("turnover_m"))
        if "requires_fi_scalar" not in cols:
            ensure_cols.append(pl.lit(False).alias("requires_fi_scalar"))
        if ensure_cols:
            lf = lf.with_columns(ensure_cols)

        # Floor the guarantor's PD using same floor rules as borrower
        has_transactor = "is_qrre_transactor" in lf.collect_schema().names()
        pd_floor_expr = _pd_floor_expression(config, has_transactor_col=has_transactor)
        guarantor_pd_floored = pl.max_horizontal(pl.col("guarantor_pd"), pd_floor_expr)

        scaling_factor = 1.06 if config.is_crr else 1.0
        eur_gbp_rate = float(config.eur_gbp_rate)

        # Compute IRB risk weight from guarantor's PD and F-IRB supervisory LGD
        sme_turnover_m = float(config.thresholds.sme_turnover_threshold) / 1_000_000
        guarantor_rw_irb = _parametric_irb_risk_weight_expr(
            pd_expr=guarantor_pd_floored,
            lgd=firb_lgd_senior,
            scaling_factor=scaling_factor,
            eur_gbp_rate=eur_gbp_rate,
            is_b31=config.is_basel_3_1,
            sme_turnover_threshold_m=sme_turnover_m,
        )

        # Select method: IRB guarantor under Basel 3.1 -> parameter substitution,
        # SA guarantor -> SA RW substitution
        is_irb_guarantor = (pl.col("guarantor_approach").fill_null("") == "irb") & pl.col(
            "guarantor_pd"
        ).is_not_null()

        return lf.with_columns(
            [
                pl.when(is_irb_guarantor)
                .then(guarantor_rw_irb)
                .otherwise(pl.col("guarantor_rw_sa"))
                .alias("guarantor_rw"),
                # Track which method is being used per-row
                pl.when((pl.col("guaranteed_portion").fill_null(0) > 0) & is_irb_guarantor)
                .then(pl.lit(True))
                .otherwise(pl.lit(False))
                .alias("_is_pd_substitution"),
            ]
        )

    # CRR or no guarantor PD: always SA RW substitution
    return lf.with_columns(
        [
            pl.col("guarantor_rw_sa").alias("guarantor_rw"),
            pl.lit(False).alias("_is_pd_substitution"),
        ]
    )


def _apply_double_default(
    lf: pl.LazyFrame,
    cols: list[str],
    config: CalculationConfig,
    has_guarantor_pd: bool,
    use_parameter_substitution: bool,
) -> pl.LazyFrame:
    """Apply double default treatment (CRR Art. 153(3), 202-203)."""
    use_double_default = config.is_crr and config.enable_double_default and has_guarantor_pd
    if not use_double_default:
        return lf.with_columns(
            [
                pl.lit(False).alias("is_double_default_eligible"),
                pl.lit(0.0).alias("double_default_unfunded_protection"),
                pl.lit(None).cast(pl.Float64).alias("irb_lgd_double_default"),
                pl.lit(False).alias("_is_dd_applied"),
            ]
        )

    # Eligibility conditions per Art. 202:
    # (a) Underlying is corporate (not sovereign, institution, retail, equity, SL)
    _exp_class_upper = pl.col("exposure_class").cast(pl.String).fill_null("").str.to_uppercase()
    _is_corporate_underlying = _exp_class_upper.str.contains("CORPORATE")

    # (b) Guarantor is institution, central govt, or rated corporate (CQS <= 2)
    _guarantor_ec = pl.col("guarantor_exposure_class").fill_null("")
    _is_eligible_guarantor_type = _guarantor_ec.is_in(
        ["institution", "mdb", "central_govt_central_bank"]
    ) | (
        _guarantor_ec.is_in(["corporate", "corporate_sme"])
        & (pl.col("guarantor_cqs").fill_null(99) <= 2)
    )

    # (c) Guarantor has internal PD
    _has_guarantor_pd = pl.col("guarantor_pd").is_not_null()

    # (d) Firm uses A-IRB (own LGD estimates) -- check is_airb column
    _is_airb = pl.col("is_airb").fill_null(False) if "is_airb" in cols else pl.lit(False)

    # Combined eligibility
    _is_dd_eligible = (
        (pl.col("guaranteed_portion").fill_null(0) > 0)
        & _is_corporate_underlying
        & _is_eligible_guarantor_type
        & _has_guarantor_pd
        & _is_airb
    )

    # Floor guarantor PD
    pd_floor_expr_dd = _pd_floor_expression(config, has_transactor_col=False)
    guarantor_pd_floored_dd = pl.max_horizontal(pl.col("guarantor_pd"), pd_floor_expr_dd)

    # Double default multiplier: (0.15 + 160 x PD_g)
    dd_multiplier = _double_default_multiplier_expr(guarantor_pd_floored_dd)

    # RW_dd = RW_obligor x multiplier (risk_weight_irb_original already = K x 12.5 x s x MA)
    rw_dd = pl.col("risk_weight_irb_original") * dd_multiplier

    # Floor: RW_dd cannot be lower than direct exposure to guarantor (Basel II para 286)
    rw_dd_floored = pl.max_horizontal(rw_dd, pl.col("guarantor_rw"))

    return lf.with_columns(
        [
            _is_dd_eligible.alias("is_double_default_eligible"),
            # Override guarantor_rw with DD RW when eligible and better than substitution
            pl.when(_is_dd_eligible & (rw_dd_floored < pl.col("guarantor_rw")))
            .then(rw_dd_floored)
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
            # Track DD method
            pl.when(_is_dd_eligible & (rw_dd_floored < pl.col("guarantor_rw")))
            .then(pl.lit(True))
            .otherwise(
                pl.col("_is_pd_substitution") if use_parameter_substitution else pl.lit(False)
            )
            .alias("_is_dd_applied"),
        ]
    )


def _adjust_expected_loss(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    ead_col: str,
    use_parameter_substitution: bool,
) -> pl.LazyFrame:
    """Adjust expected loss for guaranteed portion."""
    # SA guarantor: no EL concept -- only unguaranteed portion retains IRB EL
    # IRB guarantor (parameter sub): EL = guarantor_pd x firb_lgd x guaranteed_portion
    if use_parameter_substitution:
        from rwa_calc.data.tables.crr_firb_lgd import get_firb_lgd_table_for_framework

        firb_lgd_table = get_firb_lgd_table_for_framework(is_basel_3_1=True)
        firb_lgd_senior = float(firb_lgd_table["unsecured_senior"])

        has_transactor = "is_qrre_transactor" in lf.collect_schema().names()
        pd_floor_expr = _pd_floor_expression(config, has_transactor_col=has_transactor)
        guarantor_pd_floored = pl.max_horizontal(pl.col("guarantor_pd"), pd_floor_expr)

        return lf.with_columns(
            [
                pl.when(
                    (pl.col("guaranteed_portion").fill_null(0) > 0)
                    & (pl.col("guarantor_rw").is_not_null())
                    & (pl.col("is_guarantee_beneficial"))
                )
                .then(
                    pl.when(pl.col("_is_pd_substitution"))
                    .then(
                        # IRB guarantor: blend IRB EL for unguaranteed +
                        # substituted EL for guaranteed
                        pl.col("expected_loss_irb_original")
                        * (pl.col("unguaranteed_portion") / pl.col(ead_col)).fill_null(1.0)
                        + guarantor_pd_floored * firb_lgd_senior * pl.col("guaranteed_portion")
                    )
                    .otherwise(
                        # SA guarantor: SA has no EL -- only unguaranteed retains EL
                        pl.col("expected_loss_irb_original")
                        * (pl.col("unguaranteed_portion") / pl.col(ead_col)).fill_null(1.0)
                    )
                )
                .otherwise(pl.col("expected_loss_irb_original"))
                .alias("expected_loss"),
            ]
        )

    # CRR: SA guarantors -> reduce EL for guaranteed portion (SA has no EL concept)
    # CRR: IRB guarantors (non-DD, with PD) -> PD substitution for EL (Art. 161(3))
    # Double default exposures retain full obligor EL (DD modifies K, not EL)
    _base_el = (
        (pl.col("guaranteed_portion").fill_null(0) > 0)
        & (pl.col("guarantor_rw").is_not_null())
        & (pl.col("is_guarantee_beneficial"))
    )
    _el_unguaranteed = pl.col("expected_loss_irb_original") * (
        pl.col("unguaranteed_portion") / pl.col(ead_col)
    ).fill_null(1.0)

    has_guarantor_pd = "guarantor_pd" in lf.collect_schema().names()
    if has_guarantor_pd:
        from rwa_calc.data.tables.crr_firb_lgd import get_firb_lgd_table_for_framework

        firb_lgd_table = get_firb_lgd_table_for_framework(is_basel_3_1=config.is_basel_3_1)
        firb_lgd_senior = float(firb_lgd_table["unsecured_senior"])  # 0.45 CRR

        has_transactor = "is_qrre_transactor" in lf.collect_schema().names()
        pd_floor_expr = _pd_floor_expression(config, has_transactor_col=has_transactor)
        guarantor_pd_floored = pl.max_horizontal(pl.col("guarantor_pd"), pd_floor_expr)

        _is_irb_non_dd = (
            (pl.col("guarantor_approach").fill_null("") == "irb")
            & pl.col("guarantor_pd").is_not_null()
            & ~pl.col("_is_dd_applied")
        )

        return lf.with_columns(
            [
                pl.when(_base_el & (pl.col("guarantor_approach").fill_null("") == "sa"))
                .then(_el_unguaranteed)
                .when(_base_el & _is_irb_non_dd)
                .then(
                    # IRB guarantor: blend borrower EL (unguaranteed) +
                    # guarantor EL (guaranteed) per Art. 161(3)
                    _el_unguaranteed
                    + guarantor_pd_floored * firb_lgd_senior * pl.col("guaranteed_portion")
                )
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
    is_beneficial_guaranteed = (pl.col("guaranteed_portion").fill_null(0) > 0) & (
        pl.col("is_guarantee_beneficial")
    )

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
            pl.when(is_beneficial_guaranteed & pl.col("_is_dd_applied"))
            .then(pl.lit("DOUBLE_DEFAULT"))
            .when(is_beneficial_guaranteed & pl.col("_is_pd_substitution"))
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
