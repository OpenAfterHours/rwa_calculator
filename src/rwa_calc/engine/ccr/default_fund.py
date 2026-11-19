"""
Default-fund-contribution (CCP) own-funds calculator — CRR Art. 307-310.

Pipeline position:
    Standalone CCR sub-stage. Consumes
    ``RawCCRBundle.default_fund_contributions`` (one row per clearing-member
    default-fund contribution) and emits a per-row LazyFrame with the own-funds
    requirement (``k_cm``), the resulting RWEA, and a regulatory-band
    attribution. ``engine/stages/ccr.py`` shapes each row into a synthetic
    ``dfc__`` SA exposure (``drawn_amount = k_cm``, RW pinned to 12.5).

Key responsibilities — one branch per Art. 307 limb:
- Art. 308(2), QCCP pre-funded:
  ``K_i = max(K_CCP x DF_i / (DF_CCP + DF_CM), 8% x 2% x DF_i)``.
- Art. 309(1), non-QCCP (pre-funded or unfunded): ``K = DF + UC`` — the
  contribution itself is the own-funds requirement, row by row.
- Art. 310, QCCP unfunded: a 0% risk weight, so no own funds.
- Art. 308(3) / 309(2): RWEA = K x 12.5 (own-funds -> RWA, Art. 92(3)(ca)).
- Attribute each row to a stable ``regulatory_band``: ``dfc_qccp_prefunded``,
  ``dfc_qccp_unfunded``, ``dfc_non_qccp_prefunded``, ``dfc_non_qccp_unfunded``.

Rule text (PRA Rulebook CCR (CRR) Part; PS1/26 Annex R re-states only the
308(3) / 309(2) cross-references, so both regimes share these numerics):
- Art. 308(2): "K_i = max{ K_CCP . DF_i / (DF_CCP + DF_CM) , 8% . 2% . DF_i }"
  where "DF_CCP = the pre-funded financial resources of the CCP".
- Art. 309(1): "K = DF + UC where ... DF = the pre-funded contributions to the
  default fund of a non-qualifying CCP; and UC = the unfunded contributions".
- Art. 310: "An institution shall apply a 0% risk weight to its unfunded
  contributions to the default fund of a QCCP."

An absent ``df_ccp_prefunded`` (DF_CCP) is read as 0. That can only shrink the
Art. 308(2) denominator, so K_i can only rise — the fallback is conservative.

Out of scope (left for follow-up tickets):
- The Art. 308(2) K_CCP hypothetical-capital simulation itself (the firm
  supplies ``k_ccp_published``, as the CCP communicates it under EMIR Art. 50c).
- The Art. 303(2) cap (QCCP trade + DF own funds <= the non-QCCP equivalent),
  which can only lower the charge.

References:
- CRR Art. 307-310; CRR Art. 92(3)(ca) (own-funds -> RWA factor 12.5).
- BCBS CRE54.31-54.40.
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl
from watchfire import cites

from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import ensure_columns
from rwa_calc.data.schemas import DF_CONTRIBUTION_SCHEMA
from rwa_calc.rulebook.compile import scalar_value
from rwa_calc.rulebook.resolve import resolve

logger = logging.getLogger(__name__)

# Regulatory-band discriminators (audit / aggregation keys).
_BAND_QCCP_PREFUNDED: str = "dfc_qccp_prefunded"
_BAND_QCCP_UNFUNDED: str = "dfc_qccp_unfunded"
_BAND_NON_QCCP_PREFUNDED: str = "dfc_non_qccp_prefunded"
_BAND_NON_QCCP_UNFUNDED: str = "dfc_non_qccp_unfunded"

# Regime-invariant Section 9 parameters, resolved from the rulepack once at
# module load (resolved against "crr"; the common pack serves both regimes).
_PACK = resolve("crr", date(2026, 1, 1))
_OWN_FUNDS_TO_RWA_FACTOR = scalar_value(_PACK.scalar_param("own_funds_to_rwa_factor"))
_FLOOR_CAPITAL_RATIO = scalar_value(_PACK.scalar_param("ccp_dfc_floor_capital_ratio"))
_FLOOR_RISK_WEIGHT = scalar_value(_PACK.scalar_param("ccp_dfc_floor_risk_weight"))
_QCCP_UNFUNDED_RW = scalar_value(_PACK.scalar_param("ccp_dfc_qccp_unfunded_rw"))


@cites("CRR Art. 308(2)")
@cites("CRR Art. 309(1)")
@cites("CRR Art. 310")
def compute_dfc_capital(
    default_fund_contributions: pl.LazyFrame,
    config: CalculationConfig,  # noqa: ARG001 — numerics identical under CRR and PS1/26
) -> pl.LazyFrame:
    """Compute the default-fund own-funds requirement and RWEA per Art. 307-310.

    Args:
        default_fund_contributions: LazyFrame matching
            ``DF_CONTRIBUTION_SCHEMA`` — one row per contribution. Read:
            ``contribution_id``, ``ccp_reference``, ``is_qccp_ccp``,
            ``is_unfunded_commitment``, ``df_i_contribution_amount`` (DF_i or
            UC), and on the QCCP pre-funded branch only ``k_ccp_published``
            (K_CCP), ``df_ccp_prefunded`` (DF_CCP) and
            ``df_cm_total_contributions`` (DF_CM).
        config: Calculation configuration. The Section 9 arithmetic is
            identical under CRR and PRA PS1/26, so the framework field is not
            branched on — the parameter is kept for signature consistency
            with sibling CCR calculators.

    Returns:
        LazyFrame with one row per input row, carrying ``contribution_id``,
        ``ccp_reference``, ``is_qccp_ccp``, ``is_unfunded_commitment``,
        ``k_ccp_published``, ``k_cm`` (the Art. 307 own-funds requirement of the
        row's branch), ``dfc_rwea`` (``k_cm`` x 12.5) and ``regulatory_band``.

    References:
        CRR Art. 308(2)/(3); CRR Art. 309(1)/(2); CRR Art. 310;
        CRR Art. 92(3)(ca).
    """
    is_qccp = pl.col("is_qccp_ccp")
    is_unfunded = pl.col("is_unfunded_commitment")
    contribution = pl.col("df_i_contribution_amount")

    # Art. 308(2): the CCP's own pre-funded resources join the clearing members'
    # in the denominator; an absent DF_CCP is read as 0 (conservative, see the
    # module docstring) — coalesce, not a fill: the column stays as supplied.
    denominator = pl.coalesce(pl.col("df_ccp_prefunded"), pl.lit(0.0)) + pl.col(
        "df_cm_total_contributions"
    )
    # ``clip`` rather than ``max_horizontal``: a missing K_CCP must stay null (and
    # surface as a null EAD downstream), never collapse silently onto the floor.
    k_qccp_prefunded = (pl.col("k_ccp_published") * contribution / denominator).clip(
        lower_bound=_FLOOR_CAPITAL_RATIO * _FLOOR_RISK_WEIGHT * contribution
    )
    # Art. 310: RWEA = UC x 0%, so K = RWEA / 12.5.
    k_qccp_unfunded = contribution * _QCCP_UNFUNDED_RW / _OWN_FUNDS_TO_RWA_FACTOR

    # Art. 309(1): K = DF + UC — each row carries one of the two terms.
    k_cm = (
        pl.when(is_qccp & is_unfunded)
        .then(k_qccp_unfunded)
        .when(is_qccp)
        .then(k_qccp_prefunded)
        .otherwise(contribution)
        .alias("k_cm")
    )

    # Art. 308(3) / 309(2): RWEA = K x 12.5 (own-funds -> RWA, Art. 92(3)(ca)).
    dfc_rwea = (pl.col("k_cm") * _OWN_FUNDS_TO_RWA_FACTOR).alias("dfc_rwea")

    regulatory_band = (
        pl.when(is_qccp & is_unfunded)
        .then(pl.lit(_BAND_QCCP_UNFUNDED))
        .when(is_qccp)
        .then(pl.lit(_BAND_QCCP_PREFUNDED))
        .when(is_unfunded)
        .then(pl.lit(_BAND_NON_QCCP_UNFUNDED))
        .otherwise(pl.lit(_BAND_NON_QCCP_PREFUNDED))
        .alias("regulatory_band")
    )

    # The frame arrives as the caller built it (the API bundle is not loader-
    # sealed), so the OPTIONAL schema columns — DF_CCP among them — are added
    # here with their declared defaults rather than assumed.
    optional_columns = {
        name: spec for name, spec in DF_CONTRIBUTION_SCHEMA.items() if not spec.required
    }
    return (
        ensure_columns(default_fund_contributions, optional_columns)
        .with_columns([k_cm])
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
