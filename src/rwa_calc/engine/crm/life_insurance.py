"""
Life Insurance Method (Art. 232(3) with Art. 233(3)).

Pipeline position:
    CRMProcessor (Step 4c) -> SACalculator._apply_life_insurance_rw_mapping

Key responsibilities:
- Aggregate life insurance collateral per exposure (surrender value = market_value),
  resolving pledges at exposure, facility OR counterparty level (pro-rata by EAD)
- Reduce the surrender value by the Art. 233(3) 8% FX volatility haircut when the
  policy currency differs from the exposure currency (currency mismatch)
- Map insurer risk weight to secured portion risk weight via the Art. 232(3) table
- Set life_ins_* columns on exposure frame for SA calculator RW blending
- No EAD reduction for SA (life insurance uses RW mapping, not EAD reduction)
- IRB LGD handled separately via the waterfall (LGDS = 40%)

Assumption: the exposure, facility (``parent_facility_reference``) and counterparty
(``counterparty_reference``) reference namespaces are DISJOINT — repo convention, not
enforced here — so a ``beneficiary_reference`` resolves at exactly one pledge level.

References:
- CRR Art. 232(3): pledged life-insurance policy as other funded credit protection
- CRR Art. 233(3): 8% FX volatility haircut on the protection value (currency mismatch)
- Art. 200(b): Eligibility of life insurance policies
- Art. 212(2): Operational requirements for life insurance collateral
- PS1/26 Art. 232(3)/233(3): retained unchanged (the 8% Hfx is regime-invariant)
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import ERROR_LIFE_INSURANCE_CURRENCY_UNKNOWN, crm_warning
from rwa_calc.data.schemas import LIFE_INSURANCE_COLLATERAL_TYPES
from rwa_calc.engine.eu_sovereign import denomination_currency_expr
from rwa_calc.engine.utils import partition_by_nullable
from rwa_calc.rulebook.compile import scalar_value
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.contracts.errors import CalculationError

# Art. 232(3) mapped risk-weight table (insurer SA RW -> secured-portion RW) and
# the Art. 233(3) 8% FX volatility haircut both live in the common rulepack pack
# (``life_insurance_secured_rw_map`` / ``fx_haircut``); read them back here so the
# pack is the single source of truth. The FX haircut is regime-invariant (common
# pack), so resolving from either regime yields the same 8%.
_LIFE_INS_PACK = resolve("crr", date(2026, 1, 1))
_LIFE_INS_SECURED_RW_BANDS = _LIFE_INS_PACK.banded("life_insurance_secured_rw_map").bands
_FX_HAIRCUT = scalar_value(_LIFE_INS_PACK.scalar_param("fx_haircut"))


def _map_insurer_rw_to_secured_rw_expr() -> pl.Expr:
    """Build expression mapping insurer_risk_weight to Art. 232(3) secured portion RW.

    The mapping (CRR Art. 232(3), ``life_insurance_secured_rw_map`` pack band
    table) is:
        20%            -> 20%
        30% or 50%     -> 35%
        65%, 100%, 135% -> 70%
        150%           -> 150%

    A band applies when the insurer RW is <= its upper bound; the open-ended top
    band is the catch-all. Built from the pack so the values have one home.

    Returns:
        Polars expression producing the mapped secured portion risk weight.
    """
    rw = pl.col("insurer_risk_weight").fill_null(1.00)
    chain: pl.Expr | None = None
    catch_all = 0.0
    for bound, value in _LIFE_INS_SECURED_RW_BANDS:
        if bound is None:
            catch_all = float(value)
            continue
        predicate = rw <= float(bound)
        chain = (
            pl.when(predicate).then(pl.lit(float(value)))
            if chain is None
            else chain.when(predicate).then(pl.lit(float(value)))
        )
    if chain is None:
        return pl.lit(catch_all)
    return chain.otherwise(pl.lit(catch_all))


@cites("CRR Art. 232(3)")
@cites("CRR Art. 233(3)")
def compute_life_insurance_columns(
    exposures: pl.LazyFrame,
    collateral: pl.LazyFrame | None,
    config: CalculationConfig,
    *,
    errors: list[CalculationError] | None = None,
) -> pl.LazyFrame:
    """Compute life insurance CRM columns on the exposure frame.

    Aggregates eligible life insurance collateral per exposure and sets:
    - life_ins_collateral_value: surrender value allocated to this exposure, after
      the Art. 233(3) 8% FX reduction on a currency mismatch (capped at EAD)
    - life_ins_secured_rw: value-weighted mapped risk weight per Art. 232(3)

    A pledge is resolved at whichever level its ``beneficiary_reference`` names —
    exposure, facility (``parent_facility_reference``) or counterparty
    (``counterparty_reference``) — and a facility/counterparty pledge is shared
    pro-rata by EAD across the covered exposures (Art. 230-231 pooling). Reference
    namespaces are disjoint, so a key resolves at exactly one level; a direct
    exposure pledge therefore benefits only that exposure.

    Art. 233(3) FX reduction: the 8% cut is applied PER POLICY (cut-then-sum), each
    policy's own denomination (``original_currency`` pre-FX, else ``currency``)
    compared against the covered exposure's denomination — never on a summed pool via
    a single representative currency (that under-cuts a mixed-currency pool and is
    plan-order-dependent). A present-but-null policy currency cannot prove a match, so
    it takes the reduction conservatively and raises CRM020; when the collateral
    carries no currency column at all the FX dimension is absent and no reduction
    applies.

    Does NOT modify EAD columns. The SA calculator uses these columns
    for risk weight blending via _apply_life_insurance_rw_mapping().

    Args:
        exposures: Exposure frame with ead_gross, exposure_reference, etc.
        collateral: Collateral frame (may be None if no collateral).
        config: Calculation configuration.
        errors: Optional error accumulator for CRM020 unknown-currency warnings.

    Returns:
        Exposure frame with life_ins_collateral_value and life_ins_secured_rw columns.
    """
    if collateral is None:
        return _add_default_life_ins_columns(exposures)

    # Filter to life insurance collateral only
    coll_schema = collateral.collect_schema()
    ctype_col = "collateral_type"
    if ctype_col not in coll_schema.names():
        return _add_default_life_ins_columns(exposures)

    li_coll = collateral.filter(
        pl.col(ctype_col).str.to_lowercase().is_in(LIFE_INSURANCE_COLLATERAL_TYPES)
    )

    # Check if insurer_risk_weight column exists
    has_insurer_rw = "insurer_risk_weight" in coll_schema.names()
    if not has_insurer_rw:
        li_coll = li_coll.with_columns(pl.lit(1.00).alias("insurer_risk_weight"))

    # Use market_value as the surrender value (documented convention)
    # Apply Art. 232(3) mapped RW per item
    li_coll = li_coll.with_columns(_map_insurer_rw_to_secured_rw_expr().alias("_li_item_rw"))

    # The policy's own denomination for the Art. 233(3) FX test: original_currency
    # (pre-FX-conversion) if present, else currency; None when neither exists.
    coll_names = coll_schema.names()
    coll_ccy_col = (
        "original_currency"
        if "original_currency" in coll_names
        else "currency"
        if "currency" in coll_names
        else None
    )
    if coll_ccy_col is not None and errors is not None:
        _record_unknown_currency_warnings(li_coll, coll_ccy_col, coll_names, errors)

    # Aggregate the (small) life-insurance collateral per beneficiary key — NO
    # exposures reference here, so the deep exposures plan stays single-referenced.
    # ``.sum()`` ignores nulls, so no fill_null is needed on the value channels.
    # ``li_total`` = value + value-weighted-RW per beneficiary; ``li_matched`` splits
    # the same channels by policy currency so the Art. 233(3) cut can be applied
    # PER POLICY (cut-then-sum) against each covered exposure's own denomination —
    # never on a summed pool via a representative currency (that would be
    # anti-conservative AND plan-order-nondeterministic on a mixed-currency pool).
    li_total = li_coll.group_by("beneficiary_reference").agg(
        pl.col("market_value").sum().alias("_li_v"),
        (pl.col("market_value") * pl.col("_li_item_rw")).sum().alias("_li_vrw"),
    )
    li_matched = None
    if coll_ccy_col is not None:
        li_matched = li_coll.group_by(["beneficiary_reference", coll_ccy_col]).agg(
            pl.col("market_value").sum().alias("_li_mv"),
            (pl.col("market_value") * pl.col("_li_item_rw")).sum().alias("_li_mvrw"),
        )

    exp_schema = exposures.collect_schema()
    exp_names = exp_schema.names()
    exp_ref_col = "exposure_reference" if "exposure_reference" in exp_names else "loan_reference"
    ead_col = "ead_gross" if "ead_gross" in exp_names else "ead"
    ead = pl.col(ead_col).fill_null(0.0)
    # Materialise the exposure denomination once as a join key for the matched-
    # currency lookup (the Art. 233(3) test compares policy vs exposure currency).
    exposures = exposures.with_columns(denomination_currency_expr(exp_names).alias("_exp_ccy"))

    # Match each pledge to its covered exposures via chained left-joins onto the ONE
    # exposures base (Art. 230-231 pooling): the direct level keys on the exposure
    # reference (weight 1.0); a facility / counterparty pledge is shared pro-rata by
    # EAD across that key's exposures. Reference namespaces are disjoint, so a key
    # fires at exactly one level (a direct pledge benefits only its own exposure).
    levels: list[tuple[str, pl.Expr, str]] = [(exp_ref_col, pl.lit(1.0), "d")]
    if "parent_facility_reference" in exp_names:
        levels.append(
            ("parent_facility_reference", _pro_rata_weight(ead, "parent_facility_reference"), "f")
        )
    if "counterparty_reference" in exp_names:
        levels.append(
            ("counterparty_reference", _pro_rata_weight(ead, "counterparty_reference"), "c")
        )

    value_terms: list[pl.Expr] = []
    vrw_terms: list[pl.Expr] = []
    scratch: list[str] = ["_exp_ccy"]
    for key_col, weight, suffix in levels:
        exposures, v, w, cols = _join_pledge_level(
            exposures, li_total, li_matched, key_col, weight, coll_ccy_col, suffix
        )
        value_terms.append(v)
        vrw_terms.append(w)
        scratch.extend(cols)

    # Total allocated value + value-weighted mapped RW (nulls skipped), capped at EAD.
    total_value = pl.sum_horizontal(value_terms)
    total_vrw = pl.sum_horizontal(vrw_terms)
    capped_value = pl.min_horizontal(total_value, ead)
    avg_rw = pl.when(total_value > 0).then(total_vrw / total_value).otherwise(pl.lit(0.0))

    return exposures.with_columns(
        capped_value.alias("life_ins_collateral_value"),
        avg_rw.alias("life_ins_secured_rw"),
    ).drop(scratch)


def _pro_rata_weight(ead: pl.Expr, key_col: str) -> pl.Expr:
    """EAD-share weight within a pledge key: ead_i / sum(ead) over the key.

    Guarded by ``partition_by_nullable``: a null facility/counterparty key never
    matches a (non-null) ``beneficiary_reference`` in the subsequent join, so its
    weight is irrelevant — the else-branch returns 0.0 rather than pooling all
    null-keyed exposures into one bogus partition.
    """
    return partition_by_nullable(
        pl.when(ead.sum().over(key_col) > 0)
        .then(ead / ead.sum().over(key_col))
        .otherwise(pl.lit(0.0)),
        key_col,
        pl.lit(0.0),
    )


def _join_pledge_level(
    exposures: pl.LazyFrame,
    li_total: pl.LazyFrame,
    li_matched: pl.LazyFrame | None,
    key_col: str,
    weight: pl.Expr,
    coll_ccy_col: str | None,
    suffix: str,
) -> tuple[pl.LazyFrame, pl.Expr, pl.Expr, list[str]]:
    """Left-join the per-beneficiary life-insurance aggregates at one pledge level.

    Joins ``li_total`` (per-beneficiary value / value-weighted-RW) onto the exposures
    base keyed by ``key_col``, and — when a policy currency is available — the
    ``li_matched`` per-(beneficiary, currency) split on the COMPOUND key
    (``key_col``, ``_exp_ccy``) so each exposure picks up only the value of policies
    denominated in ITS OWN currency. The Art. 233(3) cut is then applied cut-then-sum:

        effective = weight x [ (1 - Hfx)*total + Hfx*matched ]

    which leaves matched-currency policies whole ((1-Hfx)*v + Hfx*v = v) and cuts the
    mismatched remainder by Hfx — order-independent and correct on a mixed-currency
    pool. A null policy or exposure currency never satisfies the compound join
    (Polars does not match null keys), so it falls entirely into the cut remainder
    (conservative). Weighting by ``weight`` applies Art. 230-231 pro-rata pooling.
    Returns the frame, the level's effective value / value-weighted-RW expressions
    (nulls skip cleanly in the cross-level sum), and its scratch column names.
    """
    total = li_total.rename({"_li_v": f"_tv_{suffix}", "_li_vrw": f"_tvrw_{suffix}"})
    exposures = exposures.join(total, left_on=key_col, right_on="beneficiary_reference", how="left")

    scratch = [f"_tv_{suffix}", f"_tvrw_{suffix}", f"_liev_{suffix}", f"_lievrw_{suffix}"]
    if coll_ccy_col is not None and li_matched is not None:
        matched = li_matched.rename({"_li_mv": f"_mv_{suffix}", "_li_mvrw": f"_mvrw_{suffix}"})
        exposures = exposures.join(
            matched,
            left_on=[key_col, "_exp_ccy"],
            right_on=["beneficiary_reference", coll_ccy_col],
            how="left",
        )
        keep = pl.lit(1.0 - _FX_HAIRCUT)
        add_back = pl.lit(_FX_HAIRCUT)
        eff_value = weight * (
            keep * pl.col(f"_tv_{suffix}") + add_back * pl.col(f"_mv_{suffix}").fill_null(0.0)
        )
        eff_vrw = weight * (
            keep * pl.col(f"_tvrw_{suffix}") + add_back * pl.col(f"_mvrw_{suffix}").fill_null(0.0)
        )
        scratch.extend([f"_mv_{suffix}", f"_mvrw_{suffix}"])
    else:
        eff_value = weight * pl.col(f"_tv_{suffix}")
        eff_vrw = weight * pl.col(f"_tvrw_{suffix}")

    exposures = exposures.with_columns(
        eff_value.alias(f"_liev_{suffix}"),
        eff_vrw.alias(f"_lievrw_{suffix}"),
    )
    return exposures, pl.col(f"_liev_{suffix}"), pl.col(f"_lievrw_{suffix}"), scratch


def _record_unknown_currency_warnings(
    li_coll: pl.LazyFrame,
    coll_ccy_col: str,
    coll_names: list[str],
    errors: list[CalculationError],
) -> None:
    """Append one CRM020 warning per life-insurance row with an unknown policy currency.

    Targeted collect over the null-currency rows only (the accepted DQ-emission
    idiom, P1.264) — the collateral table is a small dimension frame. The
    ``beneficiary_reference`` key is a required collateral column, so it is read
    unconditionally; the policy id (``collateral_reference``) is optional.
    """
    select_cols = [pl.col("beneficiary_reference")]
    if "collateral_reference" in coll_names:
        select_cols.append(pl.col("collateral_reference"))
    gated = li_coll.filter(pl.col(coll_ccy_col).is_null())
    unknown = gated.select(select_cols).collect()
    for row in unknown.iter_rows(named=True):
        coll_ref = row.get("collateral_reference")
        ben_ref = row.get("beneficiary_reference")
        errors.append(
            crm_warning(
                ERROR_LIFE_INSURANCE_CURRENCY_UNKNOWN,
                f"Life-insurance policy '{coll_ref}' securing '{ben_ref}' carries no "
                f"currency; its surrender value cannot be proven to match the exposure "
                f"currency, so the Art. 233(3) 8% FX volatility reduction is applied "
                f"conservatively to the secured value.",
                exposure_reference=ben_ref,
                regulatory_reference="CRR Art. 233(3)",
            )
        )


def _add_default_life_ins_columns(exposures: pl.LazyFrame) -> pl.LazyFrame:
    """Add zero-valued life insurance columns when no life insurance collateral exists."""
    return exposures.with_columns(
        pl.lit(0.0).alias("life_ins_collateral_value"),
        pl.lit(0.0).alias("life_ins_secured_rw"),
    )
