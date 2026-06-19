"""
Maturity factor for SA-CCR trades (margined and unmargined netting sets).

Pipeline position:
    Classifier -> CCRCalculator (maturity factor) -> ...

Key responsibilities:
- Compute ``MF = sqrt(min(M, 1y) / 1y)`` per CRR Art. 279c(1) for trades
  in unmargined netting sets.
- Compute ``MF = 1.5 * sqrt(MPOR_eff / 250)`` per CRR Art. 279c(2) for trades
  in margined netting sets, with the Art. 285 cascade driving MPOR_eff.

References:
- CRR Art. 279c(1): Maturity factor (unmargined)
- CRR Art. 279c(2): Maturity factor (margined)
- CRR Art. 285(2)-(5): MPOR floors, large/illiquid upgrades, dispute doubling
  and the remargining-frequency MPOR_eff formula.
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl
from watchfire import cites

from rwa_calc.rulebook.compile import scalar_value
from rwa_calc.rulebook.resolve import resolve

logger = logging.getLogger(__name__)

# SA-CCR maturity-factor parameters resolved from the rulepack once at module
# load: the margined-MF float scalars (CRR Art. 279c) plus the integer MPOR
# cascade counts (Art. 285 floor business-days, large-netting-set trade count,
# dispute threshold/multiplier) and the 250-business-day-year divisor basis.
_PACK = resolve("crr", date(2026, 1, 1))
_MF_MARGINED_SCALAR = scalar_value(_PACK.scalar_param("mf_margined_scalar"))
_MF_UNMARGINED_CAP_YEARS = scalar_value(_PACK.scalar_param("mf_unmargined_cap_years"))
_MF_UNMARGINED_DENOM_YEARS = scalar_value(_PACK.scalar_param("mf_unmargined_denom_years"))
_MF_FLOOR_DAYS_REPO_SFT = _PACK.int_param("mf_margined_floor_days_repo_sft").value
_MF_FLOOR_DAYS_OTC = _PACK.int_param("mf_margined_floor_days_otc").value
_MF_FLOOR_DAYS_LARGE_OR_ILLIQUID = _PACK.int_param("mf_margined_floor_days_large_or_illiquid").value
_MF_LARGE_NETTING_SET_TRADE_COUNT = _PACK.int_param(
    "mf_margined_large_netting_set_trade_count"
).value
_MF_DISPUTE_THRESHOLD = _PACK.int_param("mf_margined_dispute_threshold").value
_MF_DISPUTE_MULTIPLIER = _PACK.int_param("mf_margined_dispute_multiplier").value
_SA_CCR_BUSINESS_DAYS_PER_YEAR = _PACK.int_param("sa_ccr_business_days_per_year").value


# Watchfire's bundled CRR index does not yet contain Art. 279c; collapse the
# ``@cites`` to the parent Art. 279 and preserve sub-article attribution in the
# docstring (mirrors the P8.7 fix-commit pattern for Art. 280a/b/c).
@cites("CRR Art. 279")
def compute_maturity_factor_unmargined(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Maturity factor for unmargined transactions per CRR Art. 279c(1).

    MF = sqrt(min(M, 1y) / 1y)

    Args:
        trades: LazyFrame containing a ``years_to_maturity`` column (Float64) —
            residual maturity in years from reporting date to trade maturity.

    Returns:
        The input LazyFrame with a new ``maturity_factor: Float64`` column.

    References:
        CRR Art. 279c(1); BCBS CRE52.50-52.
    """
    return trades.with_columns(
        (
            pl.min_horizontal(
                pl.col("years_to_maturity"),
                pl.lit(_MF_UNMARGINED_CAP_YEARS),
            )
            / _MF_UNMARGINED_DENOM_YEARS
        )
        .sqrt()
        .alias("maturity_factor")
    )


# Watchfire's bundled CRR index does not yet contain Art. 279c or Art. 285;
# collapse the ``@cites`` to the parent Art. 279 and preserve sub-article
# attribution in the docstring (mirrors the unmargined sibling above).
@cites("CRR Art. 279")
def compute_maturity_factor_margined(trades: pl.LazyFrame) -> pl.LazyFrame:
    """Maturity factor for margined transactions per CRR Art. 279c(2).

    ``MF = (3/2) * sqrt(MPOR_eff / 250)``

    ``MPOR_eff`` is derived per the CRR Art. 285 cascade:

    1. Base MPOR (Art. 285(2)):
        - 5 BD when ALL trades in the netting set are SFT/repo/margin-lending
          (Art. 285(2)(a)) — DOCUMENTED-BUT-INERT in production: the pipeline
          adapter splits SFTs out to the FCCM branch
          (``pipeline_adapter._split_ccr_bundle_by_transaction_type``) before
          this function ever sees them, so the derivative-only sub-bundle makes
          ``all_sft_in_ns`` always False. The branch is retained for the unit
          tests (which feed SFT rows directly) and for spec completeness.
        - 10 BD otherwise (OTC derivative netting set, Art. 285(2)(b))
    2. Upgrade to 20 BD (Art. 285(3)) when either:
        - ``number_of_trades > 5000`` (Art. 285(3)(a)), or
        - ``has_illiquid_collateral_or_hard_to_replace_otc`` is True
          (Art. 285(3)(b))
    3. Dispute doubling (Art. 285(4)): if ``dispute_count_qtr > 2``, double
       the resulting MPOR base.
    4. Remargining-frequency adjustment (Art. 285(5)):
       ``MPOR_eff = base + remargining_frequency_days - 1``.
    5. Input-MPOR floor: ``MPOR_eff = max(MPOR_eff, mpor_days_input)``.

    Args:
        trades: LazyFrame with one row per trade carrying the Art. 285 cascade
            inputs as columns:

            - ``netting_set_id``                — group key for the all-SFT check
            - ``transaction_type``              — "sft" vs "derivative" (etc.)
            - ``number_of_trades``              — count of trades in the NS
            - ``has_illiquid`` — bool flag (aliased from the netting-set
              column ``has_illiquid_collateral_or_hard_to_replace_otc`` at
              the join site)
            - ``dispute_count_qtr``             — disputes in the prior quarter
            - ``remargining_frequency_days``    — CSA remargining frequency
            - ``mpor_days_input``               — firm-supplied MPOR floor (BD)

    Returns:
        The input LazyFrame with two new Float64 columns:

        - ``maturity_factor_margined`` — the gated margined MF (null on
          unmargined rows so the pipeline-adapter coalesce can fall back to
          the unmargined MF without clobbering it).
        - ``maturity_factor`` — an alias of ``maturity_factor_margined``
          retained for the P8.14 unit tests, which feed an all-margined
          denormalised frame and read the bare column.

    References:
        CRR Art. 279c(2); CRR Art. 285(2)-(5); BCBS CRE52.51-52.
    """
    # Step 1 — base MPOR per Art. 285(2): 5 BD if all trades in the netting
    # set are SFT, otherwise 10 BD. We broadcast the group-level decision
    # back to each row via ``.over("netting_set_id")``. NOTE: in production the
    # all-SFT branch is inert — SFTs are routed to FCCM upstream so the
    # derivative-only sub-bundle never satisfies ``all_sft_in_ns`` (see the
    # docstring Step 1 note).
    all_sft_in_ns = pl.col("transaction_type").eq("sft").min().over("netting_set_id")

    base_post_step1 = (
        pl.when(all_sft_in_ns)
        .then(pl.lit(_MF_FLOOR_DAYS_REPO_SFT))
        .otherwise(pl.lit(_MF_FLOOR_DAYS_OTC))
    )

    # Step 2 — upgrade to 20 BD when the netting set is large
    # (Art. 285(3)(a)) or contains illiquid collateral / hard-to-replace
    # OTC trades (Art. 285(3)(b)).
    is_large_or_illiquid = pl.col("number_of_trades") > pl.lit(_MF_LARGE_NETTING_SET_TRADE_COUNT)
    is_large_or_illiquid = is_large_or_illiquid | pl.col("has_illiquid")

    base_post_step2 = (
        pl.when(is_large_or_illiquid)
        .then(pl.lit(_MF_FLOOR_DAYS_LARGE_OR_ILLIQUID))
        .otherwise(base_post_step1)
    )

    # Step 3 — dispute doubling per Art. 285(4): when dispute_count_qtr
    # exceeds the regulatory threshold (more than two), the MPOR base
    # is doubled.
    base_post_step3 = (
        pl.when(pl.col("dispute_count_qtr") > pl.lit(_MF_DISPUTE_THRESHOLD))
        .then(base_post_step2 * pl.lit(_MF_DISPUTE_MULTIPLIER))
        .otherwise(base_post_step2)
    )

    # Step 4 — remargining frequency adjustment per Art. 285(5):
    # MPOR_eff = base + remargining_frequency_days − 1.
    mpor_eff_pre_floor = base_post_step3 + pl.col("remargining_frequency_days") - pl.lit(1)

    # Step 5 — input-MPOR floor: MPOR_eff = max(MPOR_eff, mpor_days_input).
    # Null-safety: a null ``mpor_days_input`` would null the whole MF through
    # ``max_horizontal``; fall back to the Art. 285(2)(b) 10-BD OTC floor so a
    # missing firm-supplied MPOR never silently drops the margined MF to null.
    mpor_eff = pl.max_horizontal(
        mpor_eff_pre_floor, pl.col("mpor_days_input").fill_null(_MF_FLOOR_DAYS_OTC)
    )

    # MF = 1.5 * sqrt(MPOR_eff / 250) per Art. 279c(2).
    maturity_factor = (
        pl.lit(_MF_MARGINED_SCALAR)
        * (mpor_eff.cast(pl.Float64) / pl.lit(float(_SA_CCR_BUSINESS_DAYS_PER_YEAR))).sqrt()
    ).cast(pl.Float64)

    # Gate on ``is_margined`` (mirrors ``compute_rc_margined``): emit the MF only
    # for margined rows; unmargined rows get null so the pipeline-adapter
    # coalesce falls back to ``maturity_factor_unmargined``. A null/absent
    # ``is_margined`` flows to the ``.otherwise`` (null) branch exactly like an
    # explicit False — the conservative NETTING_SET_SCHEMA default — so no
    # ``fill_null`` is needed on the gate. ``maturity_factor`` is written as an
    # alias of the gated margined column for the P8.14 unit tests (all-margined
    # frame).
    maturity_factor_margined = (
        pl.when(pl.col("is_margined"))
        .then(maturity_factor)
        .otherwise(pl.lit(None, dtype=pl.Float64))
    )

    return trades.with_columns(
        maturity_factor_margined.alias("maturity_factor_margined"),
        maturity_factor_margined.alias("maturity_factor"),
    )
