"""
Default-fund-contribution (CCP) capital calculator — CRR Art. 308 / Art. 309.

Pipeline position:
    Standalone CCR sub-stage. Consumes
    ``RawCCRBundle.default_fund_contributions`` (one row per clearing-member
    default-fund contribution) and emits a per-row LazyFrame with the
    clearing-member capital requirement (K_CM), the resulting RWEA, and a
    regulatory-band attribution.

Key responsibilities:
- Allocate the CCP hypothetical capital (K_CCP, firm-supplied) to the
  clearing member per CRR Art. 308(2):
  ``K_CM = K_CCP x (DF_i / DF_CM)``.
- Convert the own-funds requirement to RWEA via the own-funds -> RWA factor
  (12.5, CRR Art. 92(3)(ca)): ``dfc_rwea = K_CM x 12.5``. This serves both
  the QCCP pre-funded leg (Art. 308(3)) and the non-QCCP / unfunded legs
  (Art. 309(2)) — the arithmetic is identical.
- Attribute each row to a stable ``regulatory_band`` string for downstream
  audit / aggregation: ``dfc_qccp_prefunded`` (QCCP, Art. 308),
  ``dfc_non_qccp_prefunded`` (non-QCCP pre-funded, Art. 309), and
  ``dfc_non_qccp_unfunded`` (non-QCCP unfunded, Art. 309).

Out of scope (left for follow-up tickets):
- The Art. 308(2) K_CCP hypothetical-capital simulation itself (the firm
  supplies ``k_ccp_published``).
- Multi-CCP / multi-default-fund netting and the Art. 308(4)/(5) total cap.
- The Art. 309 K_CCP cap / 1250%-vs-deduction alternative.
- The Art. 308 capital-ratio (i_2 / c) adjustment and the 2% floor on the
  QCCP trade-exposure leg (that is Art. 306 / ``ccp.py``).

References:
- CRR Art. 308(2): K_CCP hypothetical capital + K_CM clearing-member
  allocation.
- CRR Art. 308(3): QCCP pre-funded own-funds (RWEA = K_CM x 12.5).
- CRR Art. 309(1)/(2): non-QCCP / unfunded treatment (same arithmetic).
- CRR Art. 92(3)(ca): own-funds -> RWA factor (12.5).
- PRA PS1/26: Art. 308/309 numerics carried into PS1/26 unchanged.
- BCBS CRE54.18-54.32.
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.rulebook.compile import scalar_value
from rwa_calc.rulebook.resolve import resolve

logger = logging.getLogger(__name__)

# Regulatory-band discriminators (audit / aggregation keys).
_BAND_QCCP_PREFUNDED: str = "dfc_qccp_prefunded"
_BAND_NON_QCCP_PREFUNDED: str = "dfc_non_qccp_prefunded"
_BAND_NON_QCCP_UNFUNDED: str = "dfc_non_qccp_unfunded"

# CRR Art. 92(3)(ca) own-funds -> RWA factor (12.5), resolved from the
# rulepack once at module load (regime-invariant; resolved against "crr").
_PACK = resolve("crr", date(2026, 1, 1))
_OWN_FUNDS_TO_RWA_FACTOR = scalar_value(_PACK.scalar_param("own_funds_to_rwa_factor"))


# NOTE: No ``@cites("CRR Art. 308")`` / ``@cites("CRR Art. 309")`` —
# watchfire's bundled rulebook index does not yet contain CRR Title II
# Chapter 6 Section 9 (CCP exposures) Art. 308-309. Article attribution is
# preserved in the docstring; re-extending the watchfire CRR index for the
# CCP articles is a separate follow-up (mirrors the failed_trades.py waiver
# for Art. 378-380 and the existing rc.py / sa_ccr.py waivers for Art.
# 274/275).
def compute_dfc_capital(
    default_fund_contributions: pl.LazyFrame,
    config: CalculationConfig,  # noqa: ARG001 — numerics identical under CRR and PS1/26
) -> pl.LazyFrame:
    """Compute clearing-member capital (K_CM) and RWEA per CRR Art. 308 / 309.

    Args:
        default_fund_contributions: LazyFrame matching
            ``DF_CONTRIBUTION_SCHEMA`` — one row per clearing-member
            default-fund contribution. Required columns: ``contribution_id``,
            ``ccp_reference``, ``df_i_contribution_amount`` (DF_i),
            ``df_cm_total_contributions`` (DF_CM), ``k_ccp_published``
            (K_CCP), plus the optional ``is_qccp_ccp`` /
            ``is_unfunded_commitment`` branch flags.
        config: Calculation configuration. The Art. 308/309 arithmetic is
            identical under CRR and PRA PS1/26, so the framework field is not
            branched on — the parameter is kept for signature consistency
            with sibling CCR calculators.

    Returns:
        LazyFrame with one row per input row, carrying:
        ``contribution_id``, ``ccp_reference``, ``is_qccp_ccp``,
        ``is_unfunded_commitment``, ``k_ccp_published``, ``k_cm`` (Art.
        308(2) clearing-member allocation), ``dfc_rwea`` (Art. 308(3)/309(2)
        K_CM x 12.5), and ``regulatory_band``.

    References:
        CRR Art. 308(2) (K_CM = K_CCP x DF_i / DF_CM);
        CRR Art. 308(3) (QCCP pre-funded RWEA = K_CM x 12.5);
        CRR Art. 309(1)/(2) (non-QCCP / unfunded — same arithmetic);
        CRR Art. 92(3)(ca) (own-funds -> RWA factor = 12.5).
    """
    is_qccp = pl.col("is_qccp_ccp")
    is_unfunded = pl.col("is_unfunded_commitment")

    # Art. 308(2): clearing-member allocation of the CCP hypothetical capital.
    k_cm = (
        pl.col("k_ccp_published")
        * (pl.col("df_i_contribution_amount") / pl.col("df_cm_total_contributions"))
    ).alias("k_cm")

    # Art. 308(3) / 309(2): RWEA = K_CM x 12.5 (own-funds -> RWA, Art. 92(3)(ca)).
    dfc_rwea = (pl.col("k_cm") * _OWN_FUNDS_TO_RWA_FACTOR).alias("dfc_rwea")

    # Regulatory band string (audit / aggregation key).
    regulatory_band = (
        pl.when(is_qccp)
        .then(pl.lit(_BAND_QCCP_PREFUNDED))
        .when(is_unfunded)
        .then(pl.lit(_BAND_NON_QCCP_UNFUNDED))
        .otherwise(pl.lit(_BAND_NON_QCCP_PREFUNDED))
        .alias("regulatory_band")
    )

    return (
        default_fund_contributions.with_columns([k_cm])
        .with_columns([dfc_rwea, regulatory_band])
        .select(
            [
                "contribution_id",
                "ccp_reference",
                "is_qccp_ccp",
                "is_unfunded_commitment",
                "k_ccp_published",
                "k_cm",
                "dfc_rwea",
                "regulatory_band",
            ]
        )
    )


__all__ = ["compute_dfc_capital"]
