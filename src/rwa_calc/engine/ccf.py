"""
Credit Conversion Factor (CCF) calculator for off-balance sheet items.

Calculates EAD for contingent exposures using regulatory CCFs:
- SA: CRR Article 111 (0%, 20%, 50%, 100%)
- F-IRB: CRR Article 166(8) (75% for undrawn commitments)
- F-IRB Exception: CRR Article 166(9) (20% for short-term trade LCs)
- A-IRB: Own-estimate CCFs with Basel 3.1 restrictions (Art. 166D)

Art. 111(1)(c) commitment-to-issue lower-of rule:
- When a commitment is to issue another OBS item (e.g., commitment to issue a guarantee),
  the CCF is the LOWER of the CCF for the underlying OBS item and the commitment type.
- Requires ``underlying_risk_type`` field on the exposure (optional; null = no cap).

Basel 3.1 A-IRB restrictions (PRA PS1/26 Art. 166D):
- Art. 166D(1)(a): Own-estimate CCFs permitted ONLY for revolving facilities
- Non-revolving A-IRB must use SA CCFs from Table A1
- Revolving facilities with 100% SA CCF (Table A1 Row 2) cannot use own-estimates
- All own-estimate CCFs floored at 50% of SA CCF (CRE32.27)
- Art. 166D(5): Three EAD floor tests for A-IRB:
  (a) CCF floor = 50% x SA CCF (implemented in _compute_ccf)
  (b) Facility-level EAD floor = on-BS EAD + 50% x F-IRB off-BS EAD (Art. 166D(3))
  (c) Fully-drawn EAD floor = on-BS EAD ignoring Art. 166D (Art. 166D(4))

CCF is part of exposure measurement, not credit risk mitigation.
It converts nominal/notional amounts to credit-equivalent EAD.

Classes:
    CCFCalculator: Calculator for credit conversion factors

Usage:
    from rwa_calc.engine.ccf import CCFCalculator

    calculator = CCFCalculator()
    exposures_with_ead = calculator.apply_ccf(exposures, config)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.domain.enums import ApproachType

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig


def drawn_for_ead() -> pl.Expr:
    """Drawn amount floored at 0 for EAD calculations.

    Negative drawn (credit balances) should not reduce EAD without a netting agreement.
    """
    return pl.col("drawn_amount").clip(lower_bound=0.0)


def interest_for_ead() -> pl.Expr:
    """Accrued interest floored at 0 for EAD calculations.

    Negative interest should not reduce EAD without a netting agreement.
    """
    return pl.col("interest").fill_null(0.0).clip(lower_bound=0.0)


def on_balance_ead() -> pl.Expr:
    """On-balance-sheet EAD: max(0, drawn) + max(0, interest).

    Combines the floored drawn amount with floored accrued interest for a single
    reusable expression. Both are fill_null(0) so this works even when
    columns contain nulls.
    """
    return pl.col("drawn_amount").clip(lower_bound=0.0) + interest_for_ead()


def sa_ccf_expression(
    risk_type_col: str = "risk_type",
    is_basel_3_1: bool = False,
) -> pl.Expr:
    """
    Return a Polars expression that maps risk_type to SA CCFs.

    CRR (Art. 111):
    - FR / full_risk: 100% (Row 1 — credit substitutes, guarantees)
    - FRC / full_risk_commitment: 100% (Row 2 — repos, factoring, forward deposits)
    - MR / medium_risk: 50%
    - MLR / medium_low_risk: 20%
    - OC / other_commit: 0% (no separate category under CRR)
    - LR / low_risk: 0%

    Basel 3.1 (PRA Art. 111 Table A1):
    - FRC / full_risk_commitment: 100% (Row 2 — certain drawdown commitments)
    - OC / other_commit: 40% (new category — Row 5)
    - LR (unconditionally cancellable): 10% (Row 6)

    Args:
        risk_type_col: Name of the risk_type column (default "risk_type")
        is_basel_3_1: Whether to apply Basel 3.1 CCF values

    Returns:
        Polars expression resolving to Float64 SA CCF values
    """
    normalized = pl.col(risk_type_col).fill_null("").str.to_lowercase()
    # Basel 3.1: SA UCC/LR gets 10% instead of 0% (PRA Art. 111 Table A1 Row 6)
    lr_ccf = 0.10 if is_basel_3_1 else 0.0
    # Basel 3.1: "Other commitments" gets 40% (Table A1 Row 5); CRR has no
    # separate category — these were 0% (lumped with LR/UCC).
    oc_ccf = 0.40 if is_basel_3_1 else 0.0
    return (
        pl.when(normalized.is_in(["fr", "full_risk", "frc", "full_risk_commitment"]))
        .then(pl.lit(1.0))
        .when(normalized.is_in(["mr", "medium_risk"]))
        .then(pl.lit(0.5))
        .when(normalized.is_in(["oc", "other_commit"]))
        .then(pl.lit(oc_ccf))
        .when(normalized.is_in(["mlr", "medium_low_risk"]))
        .then(pl.lit(0.2))
        .when(normalized.is_in(["lr", "low_risk"]))
        .then(pl.lit(lr_ccf))
        .otherwise(pl.lit(0.5))  # Default to MR (50%) for SA
    )


def _firb_ccf_for_col(risk_type_col: str = "risk_type") -> pl.Expr:
    """Return CRR F-IRB CCF expression for a given risk_type column.

    CRR Art. 166(8): 75% for commitments, with exceptions:
    - FR/FRC = 100%
    - LR/OC = 0%
    - MLR with is_short_term_trade_lc = 20% (Art. 166(9))
    - MR/MLR otherwise = 75%

    This is extracted as a helper so Art. 111(1)(c) can compute the F-IRB CCF
    for both the commitment's own risk_type and the underlying OBS item.
    """
    normalized = pl.col(risk_type_col).fill_null("").str.to_lowercase()
    return (
        pl.when(normalized.is_in(["fr", "full_risk", "frc", "full_risk_commitment"]))
        .then(pl.lit(1.0))
        .when(normalized.is_in(["lr", "low_risk", "oc", "other_commit"]))
        .then(pl.lit(0.0))
        .when(
            normalized.is_in(["mlr", "medium_low_risk"])
            & pl.col("is_short_term_trade_lc").fill_null(False)
        )
        .then(pl.lit(0.2))  # Art. 166(9) exception
        .when(normalized.is_in(["mr", "medium_risk", "mlr", "medium_low_risk"]))
        .then(pl.lit(0.75))
        .otherwise(pl.lit(0.75))  # Default to 75% for F-IRB
    )


class CCFCalculator:
    """
    Calculate credit conversion factors for off-balance sheet items.

    Implements CRR CCF rules:
    - SA (Art. 111): 0%, 20%, 50%, 100% by commitment type
    - F-IRB (Art. 166(8)): 75% for undrawn commitments (except 0% for cancellable)
    - F-IRB (Art. 166(9)): 20% for short-term trade LCs arising from goods movement
    - A-IRB: own estimates under CRR; restricted to revolving under Basel 3.1

    Basel 3.1 A-IRB restrictions (PRA PS1/26 Art. 166D(1)(a)):
    - Own-estimate CCFs ONLY for revolving facilities with SA CCF < 100%
    - Non-revolving A-IRB: must use SA CCFs from Table A1
    - Revolving with 100% SA CCF: must use SA CCF (Table A1 Row 2 carve-out)
    - All own CCFs floored at 50% of SA CCF (CRE32.27)
    """

    def __init__(self) -> None:
        """Initialize CCF calculator."""
        pass

    def apply_ccf(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply CCF to calculate EAD for off-balance sheet exposures.

        CCF determination follows CRR Art. 111 categories based on risk_type:
        - SA: FR=100%, MR=50%, MLR=20%, LR=0%
        - F-IRB: FR=100%, MR/MLR=75% (CRR Art. 166(8)), LR=0%
        - F-IRB Exception: MLR with is_short_term_trade_lc=True retains 20% (Art. 166(9))
        - A-IRB CRR: Uses ccf_modelled if provided, otherwise falls back to SA
        - A-IRB B31: Own CCF only for revolving (non-100% SA); else SA CCF (Art. 166D)
        - Art. 111(1)(c): When underlying_risk_type is specified, CCF is capped
          at the lower of the commitment's CCF and the underlying OBS item's CCF

        Args:
            exposures: Exposures with nominal_amount, risk_type, and approach columns
            config: Calculation configuration

        Returns:
            LazyFrame with ead_from_ccf and ccf columns added
        """
        schema = exposures.collect_schema()
        names = schema.names()
        original_has_risk_type = "risk_type" in names
        original_has_underlying = "underlying_risk_type" in names
        original_has_interest = "interest" in names
        has_provision_cols = "nominal_after_provision" in names and "provision_on_drawn" in names

        exposures, added_cols = self._ensure_columns(exposures, names, has_provision_cols)
        exposures = self._compute_ccf(exposures, config)
        exposures = self._compute_ead(exposures, has_provision_cols, config)
        exposures = self._build_audit_trail(
            exposures, original_has_risk_type, original_has_underlying, original_has_interest
        )

        # Clean up temp and default-populated columns
        return exposures.drop(
            "_sa_ccf_from_risk_type",
            "_firb_ccf_from_risk_type",
            "_nominal_is_zero",
            *added_cols,
        )

    def _ensure_columns(
        self,
        exposures: pl.LazyFrame,
        names: list[str],
        has_provision_cols: bool,
    ) -> tuple[pl.LazyFrame, list[str]]:
        """Pre-populate missing optional columns with sensible defaults.

        Follows the SA calculator pattern of adding defaults in a single
        with_columns() call to eliminate downstream branching.
        """
        missing: list[pl.Expr] = []
        added: list[str] = []

        defaults: list[tuple[str, pl.Expr]] = [
            ("risk_type", pl.lit("").alias("risk_type")),
            ("underlying_risk_type", pl.lit("").alias("underlying_risk_type")),
            ("approach", pl.lit("sa").alias("approach")),
            ("ccf_modelled", pl.lit(None).cast(pl.Float64).alias("ccf_modelled")),
            (
                "is_short_term_trade_lc",
                pl.lit(False).alias("is_short_term_trade_lc"),
            ),
            ("interest", pl.lit(0.0).alias("interest")),
            ("is_revolving", pl.lit(False).alias("is_revolving")),
            ("ead_modelled", pl.lit(None).cast(pl.Float64).alias("ead_modelled")),
        ]
        for col_name, default_expr in defaults:
            if col_name not in names:
                missing.append(default_expr)
                added.append(col_name)

        # Provision columns are paired (set by resolve_provisions together).
        # Only add defaults when both are absent.
        if not has_provision_cols:
            if "nominal_after_provision" not in names:
                missing.append(pl.col("nominal_amount").alias("nominal_after_provision"))
                added.append("nominal_after_provision")
            if "provision_on_drawn" not in names:
                missing.append(pl.lit(0.0).alias("provision_on_drawn"))
                added.append("provision_on_drawn")

        if missing:
            exposures = exposures.with_columns(missing)

        return exposures, added

    def _compute_ccf(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Compute CCF based on risk type and approach.

        Determines SA and F-IRB CCFs from risk_type, then selects the final CCF
        based on the exposure's approach (SA/F-IRB/A-IRB).
        """
        is_b31 = config.is_basel_3_1

        if is_b31:
            # Basel 3.1 Art. 166C: F-IRB uses SA CCFs (PRA PS1/26 Art. 111 Table A1)
            # FR=100%, MR=50%, MLR=20%, LR(UCC)=10%
            firb_ccf = sa_ccf_expression(is_basel_3_1=True)
        else:
            # CRR Art. 166(8): F-IRB = 75% for commitments, with exceptions
            firb_ccf = _firb_ccf_for_col("risk_type")

        exposures = exposures.with_columns(
            sa_ccf_expression(is_basel_3_1=is_b31).alias("_sa_ccf_from_risk_type"),
            firb_ccf.alias("_firb_ccf_from_risk_type"),
            (pl.col("nominal_amount").cast(pl.Float64, strict=False).abs() < 1e-10).alias(
                "_nominal_is_zero"
            ),
        )

        # Art. 111(1)(c): commitment-to-issue lower-of rule.
        # When underlying_risk_type is specified, cap CCFs at the underlying item's CCF.
        # "the lower of (i) the CCF applicable to the underlying OBS item and
        #  (ii) the CCF applicable to the commitment type"
        has_underlying = pl.col("underlying_risk_type").fill_null("").str.len_chars() > 0
        underlying_sa = sa_ccf_expression("underlying_risk_type", is_basel_3_1=is_b31)
        exposures = exposures.with_columns(
            pl.when(has_underlying)
            .then(pl.min_horizontal(pl.col("_sa_ccf_from_risk_type"), underlying_sa))
            .otherwise(pl.col("_sa_ccf_from_risk_type"))
            .alias("_sa_ccf_from_risk_type"),
            pl.when(has_underlying)
            .then(
                pl.min_horizontal(
                    pl.col("_firb_ccf_from_risk_type"),
                    sa_ccf_expression("underlying_risk_type", is_basel_3_1=True)
                    if is_b31
                    else _firb_ccf_for_col("underlying_risk_type"),
                )
            )
            .otherwise(pl.col("_firb_ccf_from_risk_type"))
            .alias("_firb_ccf_from_risk_type"),
        )

        # A-IRB CCF: use modelled value, with Basel 3.1 restrictions
        ccf_modelled_expr = pl.col("ccf_modelled").cast(pl.Float64, strict=False)
        if is_b31:
            # Basel 3.1 Art. 166D(1)(a): own-estimate CCFs only for revolving
            # facilities whose SA CCF is not 100% (Table A1 Row 2 carve-out).
            # Non-revolving A-IRB must use SA CCFs from Table A1.
            # Revolving with SA CCF < 100%: own CCF with 50% SA floor (CRE32.27).
            airb_revolving_ccf = pl.max_horizontal(
                ccf_modelled_expr.fill_null(pl.col("_sa_ccf_from_risk_type")),
                pl.col("_sa_ccf_from_risk_type") * 0.5,
            )
            is_eligible_for_own_ccf = pl.col("is_revolving").fill_null(False) & (
                pl.col("_sa_ccf_from_risk_type") < 1.0
            )
            airb_ccf = (
                pl.when(is_eligible_for_own_ccf)
                .then(airb_revolving_ccf)
                .otherwise(pl.col("_sa_ccf_from_risk_type"))
            )
        else:
            airb_ccf = ccf_modelled_expr.fill_null(pl.col("_sa_ccf_from_risk_type"))

        # Select final CCF based on approach
        return exposures.with_columns(
            pl.when(pl.col("_nominal_is_zero"))
            .then(pl.lit(0.0))
            .when(pl.col("approach") == ApproachType.AIRB.value)
            .then(airb_ccf)
            .when(pl.col("approach") == ApproachType.FIRB.value)
            .then(pl.col("_firb_ccf_from_risk_type"))
            .otherwise(pl.col("_sa_ccf_from_risk_type"))
            .alias("ccf"),
        )

    def _compute_ead(
        self,
        exposures: pl.LazyFrame,
        has_provision_cols: bool,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Calculate EAD from CCF-adjusted undrawn and on-balance-sheet components.

        Provision deduction (CRR Art. 111(2)) is applied only when both
        provision columns were present in the original input.

        For A-IRB under Basel 3.1, applies Art. 166D(5) EAD floors:
        (b) When ead_modelled is provided (Art. 166D(3) single-EAD approach):
            EAD >= on-BS EAD + 50% x F-IRB off-BS EAD
            (Under B31, F-IRB uses SA CCFs per Art. 166C)
        (c) Fully-drawn EAD floor (Art. 166D(4)/(5)(c)):
            EAD >= on-balance-sheet EAD (ignoring Art. 166D)
        """
        if has_provision_cols:
            on_bal = (drawn_for_ead() - pl.col("provision_on_drawn")).clip(lower_bound=0.0)
        else:
            on_bal = drawn_for_ead()
        on_bal = on_bal + interest_for_ead()

        exposures = exposures.with_columns(
            (pl.col("nominal_after_provision") * pl.col("ccf")).alias("ead_from_ccf"),
        ).with_columns(
            (on_bal + pl.col("ead_from_ccf")).alias("ead_pre_crm"),
        )

        # Art. 166D(5) EAD floors — Basel 3.1 A-IRB only
        if config.is_basel_3_1:
            is_airb = pl.col("approach") == ApproachType.AIRB.value
            has_modelled_ead = pl.col("ead_modelled").is_not_null()

            # Floor (b): facility-level EAD floor for Art. 166D(3) single-EAD approach
            # EAD >= on-BS EAD + 50% x (nominal x SA_CCF)
            # Under B31, F-IRB CCFs = SA CCFs (Art. 166C)
            floor_b = (
                on_bal + pl.col("nominal_after_provision") * pl.col("_sa_ccf_from_risk_type") * 0.5
            )

            # Floor (c): fully-drawn EAD floor — Art. 166D(5)(c)
            # EAD >= on-balance-sheet EAD (ignoring Art. 166D)
            floor_c = on_bal

            exposures = exposures.with_columns(
                pl.when(is_airb & has_modelled_ead)
                .then(
                    # Art. 166D(3)/(4): use modelled EAD, floored by (b) and (c)
                    pl.max_horizontal(
                        pl.col("ead_modelled"),
                        floor_b,
                        floor_c,
                    )
                )
                .when(is_airb)
                .then(
                    # Standard CCF approach: floor (c) as belt-and-suspenders
                    # (redundant when CCF >= 0, but guards edge cases)
                    pl.max_horizontal(pl.col("ead_pre_crm"), floor_c)
                )
                .otherwise(pl.col("ead_pre_crm"))
                .alias("ead_pre_crm"),
            )

        return exposures

    def _build_audit_trail(
        self,
        exposures: pl.LazyFrame,
        has_risk_type: bool,
        has_underlying: bool,
        has_interest: bool,
    ) -> pl.LazyFrame:
        """Build ccf_calculation audit string from available columns.

        Flags reflect the *original* input schema so the audit trail
        matches what was actually provided.
        """
        parts: list[pl.Expr] = [
            pl.lit("CCF="),
            (pl.col("ccf") * 100).round(0).cast(pl.String),
            pl.lit("%"),
        ]
        if has_risk_type:
            parts += [
                pl.lit("; risk_type="),
                pl.col("risk_type").fill_null("unknown"),
            ]
        if has_underlying:
            parts += [
                pl.lit("; underlying="),
                pl.col("underlying_risk_type").fill_null(""),
            ]
        if has_interest:
            parts += [
                pl.lit("; drawn="),
                pl.col("drawn_amount").round(0).cast(pl.String),
                pl.lit("; interest="),
                interest_for_ead().round(0).cast(pl.String),
            ]
        parts += [
            pl.lit("; nominal="),
            pl.col("nominal_amount").round(0).cast(pl.String),
            pl.lit("; ead_ccf="),
            pl.col("ead_from_ccf").round(0).cast(pl.String),
        ]

        return exposures.with_columns(
            pl.concat_str(parts).alias("ccf_calculation"),
        )


def create_ccf_calculator() -> CCFCalculator:
    """
    Create a CCF calculator instance.

    Returns:
        CCFCalculator ready for use
    """
    return CCFCalculator()
