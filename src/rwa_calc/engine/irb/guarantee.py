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
- CRR Art. 235 / PRA PS1/26 Art. 235: SA risk-weight substitution method (RWSM)
- CRR Art. 114-122: guarantor SA risk weights (shared builder —
  data/tables/guarantor_rw.py)
- Basel 3.1 CRE22.70-85: Parameter substitution approach
- CRR Art. 306, CRE54.14-15: CCP risk weights
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.engine.eu_sovereign import (
    build_domestic_cgcb_guarantor_expr,
    denomination_currency_expr,
    funding_currency_expr,
)
from rwa_calc.engine.irb.formulas import (
    _double_default_multiplier_expr,
    _parametric_irb_risk_weight_expr,
    _pd_floor_expression,
    firb_supervisory_lgd_values,
)
from rwa_calc.engine.sa.guarantor_rw import build_guarantor_rw_expr
from rwa_calc.engine.thresholds import regulatory_threshold
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.compile import scalar_value

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack


@cites("CRR Art. 161(3)")
def apply_guarantee_substitution(
    lf: pl.LazyFrame, config: CalculationConfig, *, pack: ResolvedRulepack | None = None
) -> pl.LazyFrame:
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

    # Run-level sentinel gate: guarantor_entity_type is the one crm_exit
    # column still CONDITIONAL (inject=False) — present iff the CRM guarantee
    # sub-step ran. Keying on it keeps this machinery (and its derived audit
    # columns: rwa_irb_original, guarantor_rw*, guarantee_status, ...) off
    # unguaranteed runs; see contracts/edges.py. The guaranteed_portion check
    # covers direct (non-pipeline) invocation.
    if "guaranteed_portion" not in cols or "guarantor_entity_type" not in cols:
        return lf

    has_expected_loss = "expected_loss" in cols
    has_guarantor_pd = "guarantor_pd" in cols
    # PD substitution applies whenever the guarantor has an internal PD.
    # Per-row routing (IRB-derived RW vs SA-derived RW) is decided inside
    # _apply_parameter_substitution by guarantor_approach, which is itself
    # beneficiary-aware (set in engine/crm/guarantees.py). This covers both
    # CRR Art. 161(3) and Basel 3.1 CRE22.70-85 — only the F-IRB LGD differs.
    use_parameter_substitution = has_guarantor_pd

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

    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack

    # --- Compute SA risk weight for guarantor (used for SA guarantors) ---
    lf = _compute_guarantor_rw_sa(lf, cols, config, pack=resolved_pack)

    # --- Basel 3.1 parameter substitution for IRB guarantors (CRE22.70-85) ---
    lf = _apply_parameter_substitution(
        lf, cols, config, use_parameter_substitution, pack=resolved_pack
    )

    # --- Double default treatment (CRR Art. 153(3), 202-203) ---
    lf = _apply_double_default(lf, cols, config, has_guarantor_pd, pack=resolved_pack)

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

    # Redistribute non-beneficial guarantee portions to beneficial guarantors.
    # For multi-guarantor exposures, non-beneficial guarantors' EAD is reallocated
    # to the most beneficial (lowest RW) guarantors using greedy fill.
    from rwa_calc.engine.crm.guarantees import redistribute_non_beneficial

    lf = redistribute_non_beneficial(lf)

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
                * pl.when(pl.col(ead_col) > 0)
                .then(pl.col("unguaranteed_portion") / pl.col(ead_col))
                .otherwise(pl.lit(1.0))
                .fill_null(1.0)
                + pl.col("guaranteed_portion") * pl.col("guarantor_rw")
            )
            .otherwise(pl.col("rwa_irb_original"))
            .alias("rwa"),
        ]
    )

    # Calculate blended risk weight for reporting. Guard the divisor so a
    # zero-EAD guaranteed row yields a finite 0.0 rather than 0/0 -> NaN (or
    # x/0 -> inf); .fill_null does not catch a non-finite quotient.
    lf = lf.with_columns(
        [
            pl.when(pl.col(ead_col) > 0)
            .then(pl.col("rwa") / pl.col(ead_col))
            .otherwise(pl.lit(0.0))
            .fill_null(0.0)
            .alias("risk_weight"),
        ]
    )

    # Adjust expected loss for guaranteed portion
    if has_expected_loss:
        lf = _adjust_expected_loss(
            lf, config, ead_col, use_parameter_substitution, pack=resolved_pack
        )

    # Track guarantee status and method for reporting
    lf = _add_guarantee_status_columns(lf)

    # Drop internal tracking columns
    lf = lf.drop("_is_pd_substitution", "_is_dd_applied", "guarantor_rw_sa")

    return lf


# =============================================================================
# PRIVATE HELPERS
# =============================================================================


@cites("CRR Art. 122")
@cites("CRR Art. 235")
def _compute_guarantor_rw_sa(
    lf: pl.LazyFrame,
    cols: list[str],
    config: CalculationConfig,
    *,
    pack: ResolvedRulepack | None = None,
) -> pl.LazyFrame:
    """Compute the guarantor's SA risk weight via the shared builder.

    Compiles ``build_guarantor_rw_expr`` (data/tables/guarantor_rw.py) with
    the IRB chain's column names — the same branch chain and order as the
    SA-side twin (engine/sa/namespace.py::_build_guarantor_rw_expr). This
    closes the IRB-guarantor PSE / RGLA substitution gap (the recorded
    Phase 4 fix) plus the IO 0%, named-MDB 0% and MDB Table 2B closures.
    """

    resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack

    # Ensure guarantor_exposure_class is available (set by CRM processor;
    # fallback for unit tests that construct LazyFrames directly)
    if "guarantor_exposure_class" not in cols:
        from rwa_calc.engine.entity_class_maps import ENTITY_TYPE_TO_SA_CLASS

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
    # B31 SCRA dispatch fallback: ensure ``guarantor_scra_grade`` is referenceable
    # by ``build_institution_guarantor_rw_expr``. The CRM processor populates this
    # column from counterparties.scra_grade (engine/crm/guarantees.py); fall back
    # to null for unit tests that construct LazyFrames directly without going
    # through the CRM join.
    if "guarantor_scra_grade" not in cols:
        lf = lf.with_columns(
            pl.lit(None).cast(pl.String).alias("guarantor_scra_grade"),
        )

    _gec = pl.col("guarantor_exposure_class").fill_null("")

    # Art. 114(4)/(7): Domestic CGCB guarantors -> 0% RW regardless of CQS.
    # Evaluate the domestic-currency (denomination) test against the guarantee
    # currency (the currency of the substituted exposure to the sovereign); the
    # Art. 233(3) 8% FX haircut separately handles any mismatch between the
    # guarantee and the underlying exposure. Fall back to the exposure's pre-FX
    # denomination when `guarantee_currency` is missing (legacy / no-guarantee
    # rows). Art. 235(3): the 0% extension additionally requires the exposure to
    # be *funded* in the domestic currency, so the funding limb (null-PERMISSIVE
    # fallback to the denomination — see `funding_currency_expr`) is ANDed in.
    _irb_schema_names = lf.collect_schema().names()
    _has_country = "guarantor_country_code" in _irb_schema_names
    _has_exposure_ccy_irb = (
        "original_currency" in _irb_schema_names or "currency" in _irb_schema_names
    )
    _has_guarantee_ccy_irb = "guarantee_currency" in _irb_schema_names
    if _has_guarantee_ccy_irb and _has_exposure_ccy_irb:
        _ccy_expr_irb = pl.col("guarantee_currency").fill_null(
            denomination_currency_expr(_irb_schema_names)
        )
    elif _has_guarantee_ccy_irb:
        _ccy_expr_irb = pl.col("guarantee_currency")
    elif _has_exposure_ccy_irb:
        _ccy_expr_irb = denomination_currency_expr(_irb_schema_names)
    else:
        _ccy_expr_irb = None

    _is_domestic_guarantor = (
        build_domestic_cgcb_guarantor_expr(
            "guarantor_country_code", _ccy_expr_irb, funding_currency_expr(_irb_schema_names)
        )
        if _has_country and _ccy_expr_irb is not None
        else pl.lit(False)
    )

    # The shared expression's unrated PSE/RGLA fallback reads the guarantor
    # country column; ensure it is referenceable for direct (non-pipeline)
    # invocation, mirroring the ccp / scra fallbacks above. The pipeline
    # always carries it (joined by engine/crm/guarantees.py).
    if not _has_country:
        lf = lf.with_columns(
            pl.lit(None).cast(pl.String).alias("guarantor_country_code"),
        )

    return lf.with_columns(
        build_guarantor_rw_expr(
            exposure_class_col="guarantor_exposure_class",
            entity_type_col="guarantor_entity_type",
            cqs_col="guarantor_cqs",
            country_code_col="guarantor_country_code",
            ccp_client_cleared_col="guarantor_is_ccp_client_cleared",
            scra_grade_col="guarantor_scra_grade",
            is_basel_3_1=resolved_pack.feature("sa_revised_risk_weight_tables"),
            domestic_cgcb_expr=_is_domestic_guarantor,
            # No borrower-maturity short-term flag is threaded on the IRB
            # path today (the SA twin derives one from its own stage
            # scratch); long-term Table 3 applies throughout.
            short_term_flag_col=None,
            no_guarantee_expr=pl.col("guaranteed_portion").fill_null(0) <= 0,
        ).alias("guarantor_rw_sa"),
    )


def _apply_parameter_substitution(
    lf: pl.LazyFrame,
    cols: list[str],
    config: CalculationConfig,
    use_parameter_substitution: bool,
    *,
    pack: ResolvedRulepack,
) -> pl.LazyFrame:
    """Apply parameter substitution for IRB guarantors (CRR Art. 161(3) /
    Basel 3.1 CRE22.70-85). The F-IRB supervisory LGD is selected per row
    by guarantor seniority and (Basel 3.1 only) FSE status:

    - subordinated guarantor       -> 0.75  (Art. 161(1)(b), both frameworks)
    - senior + FSE guarantor (B31) -> 0.45  (Art. 161(1)(a))
    - senior + non-FSE guarantor   -> 0.40 B31 / 0.45 CRR (Art. 161(1)(aa)/(a))

    Also enforces the "no better than direct" output floor (Art. 160(4)):
    after computing ``guarantor_rw_irb`` from PSM, derive ``RW_direct`` —
    the IRB risk weight the guarantor would attract as a *direct* borrower
    (using the guarantor's own exposure class, floored PD, and F-IRB LGD)
    — and expose ``guarantor_rw_post_nbd = max(guarantor_rw_irb, RW_direct)``.
    The downstream beneficial-gate uses ``guarantor_rw_post_nbd``.
    """
    if not use_parameter_substitution:
        # CRR or no guarantor PD: always SA RW substitution
        return lf.with_columns(
            [
                pl.col("guarantor_rw_sa").alias("guarantor_rw"),
                pl.lit(False).alias("_is_pd_substitution"),
            ]
        )

    firb_lgd_senior, firb_lgd_senior_fse, firb_lgd_subordinated = _firb_lgd_tuple(pack)

    lf = _ensure_parameter_substitution_columns(lf, cols)

    # Floor the guarantor's PD using the GUARANTOR's exposure class context
    # (Art. 160(4) / 163(1)): the guaranteed portion is economically
    # equivalent to a direct exposure to the guarantor, so the guarantor's
    # class floor governs. For a corporate guarantor under B31 the floor is
    # 0.0005 (Art. 163(1)(a)) — not the borrower's QRRE-revolver floor of
    # 0.0010. Guarantors are not QRRE in our model, so the transactor flag
    # is intentionally disabled for the guarantor floor.
    pd_floor_expr = _pd_floor_expression(
        config,
        has_transactor_col=False,
        exposure_class_col="guarantor_exposure_class",
        pack=pack,
    )
    guarantor_pd_floored = pl.max_horizontal(pl.col("guarantor_pd"), pd_floor_expr)

    scaling_factor = scalar_value(pack.scalar_param("irb_scaling_factor"))
    eur_gbp_rate = float(config.eur_gbp_rate)

    # Per-row F-IRB supervisory LGD selection (Art. 161(1)(a)/(aa)/(b)).
    # Missing seniority defaults to "senior". This is the option (ii) LGD
    # — the supervisory LGD for a direct obligation of the guarantor's
    # seniority — which is also used unconditionally for the Art. 160(4)
    # "no better than direct" floor regardless of psm_lgd_source.
    guarantor_supervisory_lgd_expr = _guarantor_supervisory_lgd_expr(
        firb_lgd_senior=firb_lgd_senior,
        firb_lgd_senior_fse=firb_lgd_senior_fse,
        firb_lgd_subordinated=firb_lgd_subordinated,
    )

    psm_lgd_expr = _psm_lgd_expr(config, guarantor_supervisory_lgd_expr)

    # Compute IRB risk weight from guarantor's PD and the chosen PSM LGD.
    # Per Art. 236(1)(a)(i) (PRA PS1/26): the PSM substitutes the guarantor's
    # PD/LGD AND derives the correlation R from the GUARANTOR's exposure
    # class context, not the borrower's. ``_parametric_irb_risk_weight_expr``
    # reads ``exposure_class``, ``turnover_m``, ``requires_fi_scalar`` and
    # ``is_qrre_transactor`` from the LazyFrame — so we compute both
    # ``guarantor_rw_irb`` (PSM) and ``rw_direct`` (Art. 160(4) NBD floor)
    # inside a single swap-restore window where those columns hold the
    # guarantor's values. The NBD floor always uses the option_ii
    # supervisory LGD so the comparison stays meaningful for option_i rows.
    sme_turnover_m = (
        float(regulatory_threshold(pack, "sme_turnover_threshold", config.eur_gbp_rate)) / 1_000_000
    )
    lf = _apply_no_better_than_direct_floor(
        lf,
        guarantor_pd_floored=guarantor_pd_floored,
        psm_lgd_expr=psm_lgd_expr,
        direct_lgd_expr=guarantor_supervisory_lgd_expr,
        scaling_factor=scaling_factor,
        eur_gbp_rate=eur_gbp_rate,
        is_b31=pack.feature("irb_correlation_sme_gbp_native"),
        sme_turnover_threshold_m=sme_turnover_m,
    )

    # Select method: IRB guarantor under Basel 3.1 -> parameter substitution,
    # SA guarantor -> SA RW substitution. The "no better than direct" floor
    # applies to the IRB-substituted RW only.
    is_irb_guarantor = (pl.col("guarantor_approach").fill_null("") == "irb") & pl.col(
        "guarantor_pd"
    ).is_not_null()

    return lf.with_columns(
        [
            pl.when(is_irb_guarantor)
            .then(pl.col("guarantor_rw_post_nbd"))
            .otherwise(pl.col("guarantor_rw_sa"))
            .alias("guarantor_rw"),
            # Track which method is being used per-row
            pl.when((pl.col("guaranteed_portion").fill_null(0) > 0) & is_irb_guarantor)
            .then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("_is_pd_substitution"),
        ]
    )


def _firb_lgd_tuple(pack: ResolvedRulepack) -> tuple[float, float, float]:
    """Return (senior, senior_fse, subordinated) F-IRB supervisory LGDs.

    The FSE-specific senior key only exists in the Basel 3.1 table; CRR has
    no FSE split (Art. 161(1)(a) covers all senior unsecured at 45%).
    """
    firb_lgd_table = firb_supervisory_lgd_values(pack)
    firb_lgd_senior = float(firb_lgd_table["unsecured_senior"])
    firb_lgd_senior_fse = float(
        firb_lgd_table.get("unsecured_senior_fse", firb_lgd_table["unsecured_senior"])
    )
    firb_lgd_subordinated = float(firb_lgd_table["subordinated"])
    return firb_lgd_senior, firb_lgd_senior_fse, firb_lgd_subordinated


def _ensure_parameter_substitution_columns(lf: pl.LazyFrame, cols: list[str]) -> pl.LazyFrame:
    """Add the columns required by ``_parametric_irb_risk_weight_expr`` when
    missing. No-op if all expected columns are already present.
    """
    defaults: list[tuple[str, pl.Expr]] = [
        ("turnover_m", pl.lit(None).cast(pl.Float64)),
        ("requires_fi_scalar", pl.lit(False)),
        ("has_one_day_maturity_floor", pl.lit(False)),
        ("guarantor_seniority", pl.lit(None).cast(pl.String)),
        ("guarantor_is_financial_sector_entity", pl.lit(False)),
    ]
    ensure_cols = [expr.alias(name) for name, expr in defaults if name not in cols]
    if not ensure_cols:
        return lf
    return lf.with_columns(ensure_cols)


def _guarantor_supervisory_lgd_expr(
    *,
    firb_lgd_senior: float,
    firb_lgd_senior_fse: float,
    firb_lgd_subordinated: float,
) -> pl.Expr:
    """Build the per-row F-IRB supervisory LGD expression (Art. 161(1))."""
    seniority = pl.col("guarantor_seniority").cast(pl.String).fill_null("senior")
    is_fse = pl.col("guarantor_is_financial_sector_entity").fill_null(False)
    return (
        pl.when(seniority == "subordinated")
        .then(pl.lit(firb_lgd_subordinated))
        .when(is_fse)
        .then(pl.lit(firb_lgd_senior_fse))
        .otherwise(pl.lit(firb_lgd_senior))
    )


def _psm_lgd_expr(config: CalculationConfig, guarantor_supervisory_lgd_expr: pl.Expr) -> pl.Expr:
    """Select the PSM LGD per ``psm_lgd_source`` (Art. 236(1)(a)(i)).

    Option (i) returns the borrower's own unprotected LGD (read from
    ``lgd``, which by this stage carries the seniority-correct borrower
    supervisory value from ``transforms.apply_firb_lgd``). ``lgd_pre_crm``
    is unsuitable because the CRM processor initialises it to the raw input
    ``lgd`` (often null for F-IRB inputs, falling back to the 45% default).

    Option (ii) returns the guarantor supervisory LGD expression — the
    historical engine default.
    """
    # irb_permissions is derived non-None in CalculationConfig.__post_init__.
    if config.irb_permissions.psm_lgd_source == "option_i":  # ty: ignore[unresolved-attribute]
        return pl.col("lgd")
    return guarantor_supervisory_lgd_expr


def _apply_no_better_than_direct_floor(
    lf: pl.LazyFrame,
    *,
    guarantor_pd_floored: pl.Expr,
    psm_lgd_expr: pl.Expr,
    direct_lgd_expr: pl.Expr,
    scaling_factor: float,
    eur_gbp_rate: float,
    is_b31: bool,
    sme_turnover_threshold_m: float,
) -> pl.LazyFrame:
    """Compute ``guarantor_rw_irb``, ``rw_direct`` and ``guarantor_rw_post_nbd``.

    ``_parametric_irb_risk_weight_expr`` reads the borrower's exposure-class
    and correlation-driving columns (``exposure_class``, ``turnover_m``,
    ``requires_fi_scalar``, ``is_qrre_transactor``) from the LazyFrame. Per
    Art. 236(1)(a)(i) (PRA PS1/26) the PSM correlation must be derived from
    the **guarantor's** class context, and per Art. 160(4) the same applies
    to the "no better than direct" floor — so we compute both inside a single
    swap-restore window where those columns hold guarantor-specific values.

    Two LGDs are accepted to support the ``psm_lgd_source`` switch:
    - ``psm_lgd_expr``: the LGD used for the PSM RW (option_i = borrower's
      pre-CRM LGD, option_ii = guarantor supervisory LGD).
    - ``direct_lgd_expr``: the LGD used for the Art. 160(4) NBD direct RW
      — always the option_ii guarantor supervisory LGD so the floor stays
      meaningful regardless of the option chosen for the PSM.

    Adds three columns:
    - ``guarantor_rw_irb``: PSM RW from guarantor's PD and the PSM LGD.
    - ``rw_direct``: IRB RW the guarantor would attract as a direct borrower
      (always uses the option_ii guarantor supervisory LGD).
    - ``guarantor_rw_post_nbd``: max(guarantor_rw_irb, rw_direct).
    """
    schema_names = lf.collect_schema().names()

    # Stash the borrower's class-driving columns so we can restore them after
    # computing the guarantor-direct RW. The maturity column is left as-is —
    # the parametric formula caps M at 5y and floors at 1y; using the
    # borrower's M is conservative for the direct-to-guarantor RW.
    stash_cols = [
        pl.col("exposure_class").alias("_nbd_borrower_exposure_class"),
        pl.col("turnover_m").alias("_nbd_borrower_turnover_m"),
        pl.col("requires_fi_scalar").alias("_nbd_borrower_requires_fi_scalar"),
    ]
    if "is_qrre_transactor" in schema_names:
        stash_cols.append(pl.col("is_qrre_transactor").alias("_nbd_borrower_is_qrre_transactor"))

    lf = lf.with_columns(stash_cols)

    # Swap in guarantor-driving values. Guarantor-specific turnover is not
    # carried through CRM today, so disable the SME correlation adjustment
    # by setting turnover_m to NULL. Ditto requires_fi_scalar (the FI scalar
    # is a property of the borrower's own corporate exposure under
    # Art. 153(2) and does not transfer to the guarantor's PSM correlation).
    swap_cols = [
        pl.col("guarantor_exposure_class").alias("exposure_class"),
        pl.lit(None).cast(pl.Float64).alias("turnover_m"),
        pl.lit(False).alias("requires_fi_scalar"),
    ]
    if "is_qrre_transactor" in schema_names:
        swap_cols.append(pl.lit(False).alias("is_qrre_transactor"))

    lf = lf.with_columns(swap_cols)

    # Evaluate the parametric IRB RW with the guarantor's class context.
    # Both the PSM RW (Art. 236(1)(a)(i)) and the NBD direct RW (Art. 160(4))
    # use the same guarantor-class formula here — the guarantor_rw_irb /
    # rw_direct split is preserved for downstream reporting and the
    # max-horizontal floor below.
    psm_rw_expr = _parametric_irb_risk_weight_expr(
        pd_expr=guarantor_pd_floored,
        lgd=psm_lgd_expr,
        scaling_factor=scaling_factor,
        eur_gbp_rate=eur_gbp_rate,
        is_b31=is_b31,
        sme_turnover_threshold_m=sme_turnover_threshold_m,
    )
    rw_direct_expr = _parametric_irb_risk_weight_expr(
        pd_expr=guarantor_pd_floored,
        lgd=direct_lgd_expr,
        scaling_factor=scaling_factor,
        eur_gbp_rate=eur_gbp_rate,
        is_b31=is_b31,
        sme_turnover_threshold_m=sme_turnover_threshold_m,
    )
    lf = lf.with_columns(
        [
            psm_rw_expr.alias("guarantor_rw_irb"),
            rw_direct_expr.alias("rw_direct"),
        ]
    )

    # Restore the borrower's original class-driving columns.
    restore_cols = [
        pl.col("_nbd_borrower_exposure_class").alias("exposure_class"),
        pl.col("_nbd_borrower_turnover_m").alias("turnover_m"),
        pl.col("_nbd_borrower_requires_fi_scalar").alias("requires_fi_scalar"),
    ]
    if "is_qrre_transactor" in schema_names:
        restore_cols.append(
            pl.col("_nbd_borrower_is_qrre_transactor").alias("is_qrre_transactor"),
        )
    lf = lf.with_columns(restore_cols)

    # Drop the stash columns and emit the NBD-floored guarantor RW.
    drop_cols = [
        "_nbd_borrower_exposure_class",
        "_nbd_borrower_turnover_m",
        "_nbd_borrower_requires_fi_scalar",
    ]
    if "is_qrre_transactor" in schema_names:
        drop_cols.append("_nbd_borrower_is_qrre_transactor")
    lf = lf.drop(drop_cols)

    return lf.with_columns(
        pl.max_horizontal(pl.col("guarantor_rw_irb"), pl.col("rw_direct")).alias(
            "guarantor_rw_post_nbd"
        ),
    )


def _apply_double_default(
    lf: pl.LazyFrame,
    cols: list[str],
    config: CalculationConfig,
    has_guarantor_pd: bool,
    *,
    pack: ResolvedRulepack,
) -> pl.LazyFrame:
    """Apply double default treatment (CRR Art. 153(3), 202-203)."""
    use_double_default = (
        pack.feature("double_default_treatment")
        and config.enable_double_default
        and has_guarantor_pd
    )
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

    # Floor guarantor PD using the guarantor's own class floor (Art. 163(1)).
    pd_floor_expr_dd = _pd_floor_expression(
        config,
        has_transactor_col=False,
        exposure_class_col="guarantor_exposure_class",
        pack=pack,
    )
    guarantor_pd_floored_dd = pl.max_horizontal(pl.col("guarantor_pd"), pd_floor_expr_dd)

    # Double default multiplier: (0.15 + 160 x PD_g)
    dd_multiplier = _double_default_multiplier_expr(guarantor_pd_floored_dd)

    # RW_dd = RW_obligor x multiplier (risk_weight_irb_original already = K x 12.5 x s x MA).
    # CRR Art. 153(3) carries NO "not lower than a direct exposure to the protection
    # provider" floor (that was Basel II para 286, not onshored), so rw_dd is compared
    # unfloored against the substitution RW in the beneficial gate below.
    rw_dd = pl.col("risk_weight_irb_original") * dd_multiplier

    return lf.with_columns(
        [
            _is_dd_eligible.alias("is_double_default_eligible"),
            # Override guarantor_rw with DD RW when eligible and beneficial vs. substitution
            pl.when(_is_dd_eligible & (rw_dd < pl.col("guarantor_rw")))
            .then(rw_dd)
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
            # Track DD method — True only when actual double-default treatment is
            # applied (eligible AND beneficial vs. plain substitution). PD substitution
            # is tracked independently via _is_pd_substitution.
            pl.when(_is_dd_eligible & (rw_dd < pl.col("guarantor_rw")))
            .then(pl.lit(True))
            .otherwise(pl.lit(False))
            .alias("_is_dd_applied"),
        ]
    )


def _adjust_expected_loss(
    lf: pl.LazyFrame,
    config: CalculationConfig,
    ead_col: str,
    use_parameter_substitution: bool,
    *,
    pack: ResolvedRulepack,
) -> pl.LazyFrame:
    """Adjust expected loss for guaranteed portion.

    SA guarantor: SA has no EL concept; only the unguaranteed portion retains EL.
    IRB guarantor: blend borrower EL (unguaranteed) + guarantor EL (guaranteed)
        per CRR Art. 161(3) / Basel 3.1 CRE22.70-85, using the framework's
        F-IRB supervisory LGD (0.45 CRR / 0.40 Basel 3.1).
    Double-default exposures (CRR Art. 153(3)) retain the full obligor EL —
        DD modifies K, not EL.
    """
    _base_el = (
        (pl.col("guaranteed_portion").fill_null(0) > 0)
        & (pl.col("guarantor_rw").is_not_null())
        & (pl.col("is_guarantee_beneficial"))
    )
    _el_unguaranteed = pl.col("expected_loss_irb_original") * (
        pl.col("unguaranteed_portion") / pl.col(ead_col)
    ).fill_null(1.0)

    if use_parameter_substitution:
        firb_lgd_table = firb_supervisory_lgd_values(pack)
        firb_lgd_senior = float(firb_lgd_table["unsecured_senior"])
        firb_lgd_senior_fse = float(
            firb_lgd_table.get("unsecured_senior_fse", firb_lgd_table["unsecured_senior"])
        )
        firb_lgd_subordinated = float(firb_lgd_table["subordinated"])

        # Mirror the guarantor-context PD floor used in _apply_parameter_substitution
        # so EL is computed against the same floored guarantor PD as RW.
        pd_floor_expr = _pd_floor_expression(
            config,
            has_transactor_col=False,
            exposure_class_col="guarantor_exposure_class",
            pack=pack,
        )
        guarantor_pd_floored = pl.max_horizontal(pl.col("guarantor_pd"), pd_floor_expr)

        _is_irb_non_dd = pl.col("_is_pd_substitution") & ~pl.col("_is_dd_applied")

        # Mirror the per-row F-IRB LGD selection used in _apply_parameter_substitution
        # so EL is computed against the same supervisory LGD as RW. Both columns
        # are guaranteed present on this path: use_parameter_substitution is True,
        # so _apply_parameter_substitution already ran
        # _ensure_parameter_substitution_columns on this same frame.
        seniority_el = pl.col("guarantor_seniority").cast(pl.String).fill_null("senior")
        is_fse_el = pl.col("guarantor_is_financial_sector_entity").fill_null(False)
        guarantor_supervisory_lgd_el = (
            pl.when(seniority_el == "subordinated")
            .then(pl.lit(firb_lgd_subordinated))
            .when(is_fse_el)
            .then(pl.lit(firb_lgd_senior_fse))
            .otherwise(pl.lit(firb_lgd_senior))
        )

        # Mirror the psm_lgd_source switch from _apply_parameter_substitution so
        # EL uses the same LGD_covered as RW (Art. 236(1A)(b) PRA PS1/26).
        # See note in _apply_parameter_substitution on column choice — ``lgd``
        # carries the seniority-correct borrower supervisory LGD by this stage.
        # irb_permissions is derived non-None in CalculationConfig.__post_init__.
        if config.irb_permissions.psm_lgd_source == "option_i":  # ty: ignore[unresolved-attribute]
            guarantor_lgd_el = pl.col("lgd")
        else:
            guarantor_lgd_el = guarantor_supervisory_lgd_el

        return lf.with_columns(
            [
                pl.when(_base_el & _is_irb_non_dd)
                .then(
                    _el_unguaranteed
                    + guarantor_pd_floored * guarantor_lgd_el * pl.col("guaranteed_portion")
                )
                .when(_base_el & (pl.col("guarantor_approach").fill_null("") == "sa"))
                .then(_el_unguaranteed)
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
    has_guaranteed_portion = pl.col("guaranteed_portion").fill_null(0) > 0
    is_beneficial_guaranteed = has_guaranteed_portion & pl.col("is_guarantee_beneficial")

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
            # guarantee_method_used reports the substitution PATH taken: PSM is
            # recorded whenever the parameter-substitution route was followed
            # (IRB guarantor with internal PD), independent of the beneficial
            # gate. The GUARANTEE_NOT_APPLIED_NON_BENEFICIAL signal lives on
            # ``guarantee_status``. PRA PS1/26 Art. 236(1)(a): an IRB guarantor
            # always traverses parameter substitution.
            pl.when(is_beneficial_guaranteed & pl.col("_is_dd_applied"))
            .then(pl.lit("DOUBLE_DEFAULT"))
            .when(has_guaranteed_portion & pl.col("_is_pd_substitution"))
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
