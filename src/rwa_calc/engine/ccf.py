"""
Credit Conversion Factor (CCF) calculator for off-balance sheet items.

Calculates EAD for contingent exposures using regulatory CCFs:
- SA: CRR Article 111 (0%, 20%, 50%, 100%)
- F-IRB Art. 166(8): bespoke CCFs for the named commitment types -
    (a) UCC credit lines -> 0%
    (b) Short-term trade LCs (movement of goods) -> 20%
    (c) Revolving purchased-receivables UCC -> 0%
    (d) Other credit lines / NIFs / RUFs -> 75%
- F-IRB Art. 166(10): residual fallback for items NOT covered by Art. 166(8) -
    100% / 50% / 20% / 0% by Annex I risk category (FR / MR / MLR / LR).
    Engine selects this branch when ``is_obs_commitment=False`` (issued OBS item).
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

Pipeline position:
    HierarchyResolver -> Classifier -> CCFCalculator -> CRMProcessor

Key responsibilities:
- Convert nominal/notional OBS amounts to credit-equivalent EAD via regulatory CCFs
- Apply SA CCFs from CRR Art. 111 (Annex I categories)
- Apply F-IRB bespoke CCFs from Art. 166(8) and Annex I fallback from Art. 166(10)
- Enforce PS1/26 Art. 166D A-IRB own-estimate restrictions and EAD floor tests
- Apply the Art. 111(1)(c) commitment-to-issue lower-of cap

References:
- CRR Art. 111: SA exposure value and CCF categories (Annex I)
- CRR Art. 166: IRB exposure value (F-IRB bespoke and Annex I fallback CCFs)
- PRA PS1/26 Art. 166D (Basel 3.1): A-IRB own-estimate CCF restrictions and
  the three EAD floor tests (CCF floor, facility-level floor, fully-drawn floor)
- BCBS CRE32.27: 50% of SA CCF floor for own-estimate CCFs

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
from watchfire import cites

from rwa_calc.data.tables.airb_floors import (
    AIRB_OBS_FLOOR_B_MULTIPLIER,
    AIRB_REVOLVING_CCF_FLOOR_MULTIPLIER,
)
from rwa_calc.data.tables.ccf import (
    OC_SHORT_MATURITY_CCF,
    OC_SHORT_MATURITY_THRESHOLD_DAYS,
    SA_CCF_B31,
    build_firb_ccf_expr,
    build_product_to_risk_type_expr,
    build_sa_ccf_expr,
)
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


@cites("CRR Art. 111")
def sa_ccf_expression(
    risk_type_col: str = "risk_type",
    is_basel_3_1: bool = False,
) -> pl.Expr:
    """Polars expression mapping risk_type to SA CCFs.

    Thin wrapper over ``data.tables.ccf.build_sa_ccf_expr``. The values
    themselves (CRR Art. 111 and PRA PS1/26 Table A1) live in the data
    layer; this wrapper preserves the historical engine-side import path
    and citation attribution.
    """
    return build_sa_ccf_expr(risk_type_col, is_basel_3_1)


@cites("CRR Art. 166")
def _firb_ccf_for_col(risk_type_col: str = "risk_type") -> pl.Expr:
    """Polars expression for CRR F-IRB CCFs (Art. 166(8) + (10)).

    Thin wrapper over ``data.tables.ccf.build_firb_ccf_expr``.
    """
    return build_firb_ccf_expr(risk_type_col)


class CCFCalculator:
    """
    Calculate credit conversion factors for off-balance sheet items.

    Implements CRR CCF rules:
    - SA (Art. 111): 0%, 20%, 50%, 100% by commitment type
    - F-IRB (Art. 166(8)(a)): 0% for unconditionally cancellable credit lines
    - F-IRB (Art. 166(8)(b)): 20% for short-term trade LCs arising from goods movement
    - F-IRB (Art. 166(8)(d)): 75% for other credit lines / NIFs / RUFs
      (selected when ``is_obs_commitment=True``)
    - F-IRB (Art. 166(10)): 100/50/20/0% fallback by Annex I category for issued
      OBS items not covered by Art. 166(8) (selected when ``is_obs_commitment=False``)
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

    @cites("CRR Art. 111")
    @cites("CRR Art. 166")
    def apply_ccf(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """
        Apply CCF to calculate EAD for off-balance sheet exposures.

        CCF determination follows CRR Art. 111 categories based on risk_type:
        - SA: FR=100%, MR=50%, MLR=20%, LR=0%
        - F-IRB Art. 166(8)(d): MR/MLR/OC commitments (credit lines / NIFs / RUFs)
          when ``is_obs_commitment=True`` -> 75%
        - F-IRB Art. 166(10) fallback: issued OBS items (``is_obs_commitment=False``)
          -> 100% FR / 50% MR / 20% MLR / 0% LR
        - F-IRB Art. 166(8)(b): MLR with ``is_short_term_trade_lc=True`` -> 20%
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
            # CRR Annex I / Art. 111(1): optional concrete OBS product key. Default
            # empty so the obs_product -> risk_type fill is a no-op when callers
            # (e.g. unit tests) construct exposures without it.
            ("obs_product", pl.lit("").alias("obs_product")),
            ("approach", pl.lit("sa").alias("approach")),
            ("ccf_modelled", pl.lit(None).cast(pl.Float64).alias("ccf_modelled")),
            (
                "is_short_term_trade_lc",
                pl.lit(False).alias("is_short_term_trade_lc"),
            ),
            # CRR Art. 166(8)(d) vs Art. 166(10): default True (commitment / Art.
            # 166(8)(d) bucket) when the column is absent — the hierarchy stage
            # is the canonical source of the per-source-table default (False
            # for contingents, True for facilities), so this only kicks in when
            # callers (e.g. unit tests) construct exposures directly.
            (
                "is_obs_commitment",
                pl.lit(True).alias("is_obs_commitment"),
            ),
            ("interest", pl.lit(0.0).alias("interest")),
            ("is_revolving", pl.lit(False).alias("is_revolving")),
            ("ead_modelled", pl.lit(None).cast(pl.Float64).alias("ead_modelled")),
            # PRA PS1/26 Art. 111(1) Table A1 Row 4(b): default False so the
            # residential-property commitment override is a no-op when callers
            # (e.g. unit tests) construct exposures without the flag.
            (
                "is_uk_residential_mortgage_commitment",
                pl.lit(False).alias("is_uk_residential_mortgage_commitment"),
            ),
            # PRA PS1/26 Art. 166E(5): default False so the revolving
            # purchased-receivables commitment CCF routing is a no-op when
            # callers (e.g. unit tests) construct exposures without the flag.
            (
                "is_purchased_receivable_commitment",
                pl.lit(False).alias("is_purchased_receivable_commitment"),
            ),
        ]
        for col_name, default_expr in defaults:
            if col_name not in names:
                missing.append(default_expr)
                added.append(col_name)

        # Provision columns are paired (set by resolve_provisions together).
        # Only add defaults when both are absent.  nominal_after_provision is
        # not tracked in added_cols because the CRM stage needs it downstream
        # (CRR Art. 223(4) ead_for_crm); when no provision data is supplied
        # the default value (= nominal_amount) is the regulatorily correct
        # "no provision" baseline.
        if not has_provision_cols:
            if "nominal_after_provision" not in names:
                missing.append(pl.col("nominal_amount").alias("nominal_after_provision"))
            if "provision_on_drawn" not in names:
                missing.append(pl.lit(0.0).alias("provision_on_drawn"))
                added.append("provision_on_drawn")

        if missing:
            exposures = exposures.with_columns(missing)

        return exposures, added

    # CRR Annex I product bands take effect via Art. 111(1); the obs_product fill
    # is attributed to Art. 111 (watchfire requires an article-based citation).
    @cites("CRR Art. 111")
    @cites("PS1/26, paragraph 111")
    def _compute_ccf(
        self,
        exposures: pl.LazyFrame,
        config: CalculationConfig,
    ) -> pl.LazyFrame:
        """Compute CCF based on risk type and approach.

        Determines SA and F-IRB CCFs from risk_type, then selects the final CCF
        based on the exposure's approach (SA/F-IRB/A-IRB).

        CRR Annex I / Art. 111(1) obs_product fill: before resolving CCFs, any row
        whose ``risk_type`` is null/empty has its ``risk_type`` resolved from the
        concrete ``obs_product`` key via ANNEX1_PRODUCT_RISK_TYPE (framework-
        invariant). An explicit ``risk_type`` always wins — the fill is gated on
        the existing value being null/empty.

        Applies the PRA PS1/26 Art. 111(1) Table A1 Row 4(b) override: a UK
        residential-property commitment (``is_uk_residential_mortgage_commitment``)
        gets a 50% SA CCF under Basel 3.1, except where the otherwise-resolved
        CCF is 10% (Row 6 UCC) or 100% (Row 2) — the Row 4(b) carve-out.
        """
        # CRR Annex I / Art. 111(1): resolve risk_type from the concrete OBS
        # product when (and only when) no explicit risk_type was supplied. Explicit
        # risk_type always wins; an unmapped/null product yields null and leaves
        # risk_type unchanged.
        risk_type_is_blank = (
            pl.col("risk_type").cast(pl.Utf8, strict=False).fill_null("").str.len_chars() == 0
        )
        product_risk_type = build_product_to_risk_type_expr("obs_product")
        exposures = exposures.with_columns(
            pl.when(risk_type_is_blank & product_risk_type.is_not_null())
            .then(product_risk_type)
            .otherwise(pl.col("risk_type"))
            .alias("risk_type"),
        )

        is_b31 = config.is_basel_3_1

        if is_b31:
            # Basel 3.1 Art. 166C: F-IRB uses SA CCFs (PRA PS1/26 Art. 111 Table A1)
            # FR=100%, MR=50%, MLR=20%, LR(UCC)=10%
            firb_ccf = sa_ccf_expression(is_basel_3_1=True)
        else:
            # CRR F-IRB: Art. 166(8)(d) -> 75% for credit lines / NIFs / RUFs
            # (is_obs_commitment=True); Art. 166(10) -> 100/50/20/0% fallback for
            # issued OBS items not in scope of paragraphs 1-8.
            firb_ccf = _firb_ccf_for_col("risk_type")

        exposures = exposures.with_columns(
            sa_ccf_expression(is_basel_3_1=is_b31).alias("_sa_ccf_from_risk_type"),
            firb_ccf.alias("_firb_ccf_from_risk_type"),
            (pl.col("nominal_amount").cast(pl.Float64, strict=False).abs() < 1e-10).alias(
                "_nominal_is_zero"
            ),
        )

        # CRR maturity-dependent OC override: under CRR, "other commitments" mapped
        # to MR (50%, >1yr) or MLR (20%, <=1yr). The sa_ccf_expression gives OC 50%
        # as the conservative default; override to 20% when remaining maturity <= 1yr.
        if not is_b31:
            normalized_rt = pl.col("risk_type").fill_null("").str.to_lowercase()
            is_oc = normalized_rt.is_in(["oc", "other_commit"])
            schema_names = exposures.collect_schema().names()
            if "maturity_date" in schema_names:
                is_short_maturity = pl.col("maturity_date").is_not_null() & (
                    (
                        pl.col("maturity_date").cast(pl.Date) - pl.lit(config.reporting_date)
                    ).dt.total_days()
                    <= OC_SHORT_MATURITY_THRESHOLD_DAYS
                )
                exposures = exposures.with_columns(
                    pl.when(is_oc & is_short_maturity)
                    .then(pl.lit(float(OC_SHORT_MATURITY_CCF)))
                    .otherwise(pl.col("_sa_ccf_from_risk_type"))
                    .alias("_sa_ccf_from_risk_type"),
                )

        # PRA PS1/26 Art. 111(1) Table A1 Row 4(b): commitments to extend credit
        # secured by residential property attract a 50% CCF — "to the extent
        # that they are not subject to a conversion factor of 10% or 100%". When
        # the flag is set under Basel 3.1, override the otherwise-resolved SA CCF
        # to the MR / Row 4(b) rate (50%), unless that CCF is already 10% (Row 6
        # UCC) or 100% (Row 2), in which case the carve-out leaves it untouched.
        # No effect under CRR (Table A1 is Basel 3.1 only) — see the gate below.
        if is_b31:
            row_4b_ccf = float(SA_CCF_B31["MR"])
            carve_out_ccfs = (float(SA_CCF_B31["LR"]), float(SA_CCF_B31["FR"]))
            is_resi_commitment = pl.col("is_uk_residential_mortgage_commitment").fill_null(False)
            sa_not_in_carve_out = ~pl.col("_sa_ccf_from_risk_type").is_in(carve_out_ccfs)
            exposures = exposures.with_columns(
                pl.when(is_resi_commitment & sa_not_in_carve_out)
                .then(pl.lit(row_4b_ccf))
                .otherwise(pl.col("_sa_ccf_from_risk_type"))
                .alias("_sa_ccf_from_risk_type"),
            )

            exposures = self._apply_purchased_receivable_ccf(exposures)

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
                pl.col("_sa_ccf_from_risk_type") * float(AIRB_REVOLVING_CCF_FLOOR_MULTIPLIER),
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

    # PRA PS1/26 Art. 166E(5) — no CRR equivalent; the watchfire PS-instrument
    # grammar only accepts numeric paragraphs, so Art. 166E para 5 is encoded as
    # section 166.5 (see docs/development/citation-tracking.md on the PS1/26 form).
    @cites("PS1/26, paragraph 166.5")
    def _apply_purchased_receivable_ccf(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Apply the Art. 166E(5) revolving purchased-receivables CCF routing.

        PRA PS1/26 Art. 166E(5): the undrawn purchase commitment of a *revolving*
        purchased-receivables facility receives a fixed CCF — 40% by default
        (Art. 111(1) Table A1 Row 5 "Other Commitments" / OC), dropping to 10%
        where the commitment also meets the Table A1 Row 7 UCC criteria
        (``risk_type == "LR"``). When ``is_purchased_receivable_commitment`` and
        ``is_revolving`` are both True, the otherwise-resolved SA / F-IRB CCF is
        overridden to this rate regardless of the row's generic risk_type bucket
        (e.g. a flagged MR row routes to 40%, not the generic 50%).

        Basel-3.1-only: callers gate this on ``config.is_basel_3_1``; there is no
        equivalent CRR purchased-receivables undrawn-commitment CCF, so the flag
        is a no-op under CRR.
        """
        oc_ccf = float(SA_CCF_B31["OC"])
        ucc_ccf = float(SA_CCF_B31["LR"])

        is_pr_commitment = pl.col("is_purchased_receivable_commitment").fill_null(False) & pl.col(
            "is_revolving"
        ).fill_null(False)
        # Table A1 Row 7 UCC criterion: the commitment is unconditionally
        # cancellable (LR risk_type) -> 10%; otherwise the Row 5 OC 40% default.
        is_ucc = pl.col("risk_type").fill_null("").str.to_lowercase().is_in(["lr", "low_risk"])
        pr_ccf = pl.when(is_ucc).then(pl.lit(ucc_ccf)).otherwise(pl.lit(oc_ccf))

        return exposures.with_columns(
            pl.when(is_pr_commitment)
            .then(pr_ccf)
            .otherwise(pl.col("_sa_ccf_from_risk_type"))
            .alias("_sa_ccf_from_risk_type"),
            pl.when(is_pr_commitment)
            .then(pr_ccf)
            .otherwise(pl.col("_firb_ccf_from_risk_type"))
            .alias("_firb_ccf_from_risk_type"),
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

        # Persist the on-BS portion of EAD so the CRM stage can compose
        # ead_for_crm = on_bs_for_ead + nominal_after_provision (CCF=100% basis,
        # CRR Art. 223(4) / PS1/26 Art. 223(4)).
        exposures = exposures.with_columns(
            on_bal.alias("on_bs_for_ead"),
            (pl.col("nominal_after_provision") * pl.col("ccf")).alias("ead_from_ccf"),
        ).with_columns(
            (pl.col("on_bs_for_ead") + pl.col("ead_from_ccf")).alias("ead_pre_crm"),
        )

        # Art. 166D(5) EAD floors — Basel 3.1 A-IRB only
        if config.is_basel_3_1:
            is_airb = pl.col("approach") == ApproachType.AIRB.value
            has_modelled_ead = pl.col("ead_modelled").is_not_null()

            # Floor (b): facility-level EAD floor for Art. 166D(3) single-EAD approach
            # EAD >= on-BS EAD + 50% x (nominal x SA_CCF)
            # Under B31, F-IRB CCFs = SA CCFs (Art. 166C)
            floor_b = pl.col("on_bs_for_ead") + pl.col("nominal_after_provision") * pl.col(
                "_sa_ccf_from_risk_type"
            ) * float(AIRB_OBS_FLOOR_B_MULTIPLIER)

            # Floor (c): fully-drawn EAD floor — Art. 166D(5)(c)
            # EAD >= on-balance-sheet EAD (ignoring Art. 166D)
            floor_c = pl.col("on_bs_for_ead")

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
