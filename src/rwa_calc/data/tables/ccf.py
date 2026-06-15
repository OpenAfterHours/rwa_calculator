"""
Off-balance-sheet product -> risk_type mapping (CRR Annex I / Art. 111(1)).

Canonical home for the framework-INVARIANT structural mapping used by
``engine/ccf.py`` to resolve a concrete OBS *product* to its abstract Annex I
``risk_type`` bucket, plus the OC short-maturity day threshold. The regulatory
CCF *percentages* (SA Art. 111 / Table A1, F-IRB Art. 166(8)/(10)) live in the
rulepack (``sa_ccf`` / ``firb_obs_fallback_ccf`` lookups + the bespoke scalars
in packs/{common,crr,b31}.py); the risk_type -> CCF expressions live in
``engine/ccf.py``.

Module-level constants:

- ``ANNEX1_PRODUCT_RISK_TYPE``: concrete OBS product -> Annex I risk_type
  bucket (framework-invariant; CRR Annex I == PRA PS1/26 Table A1).
- ``OC_SHORT_MATURITY_THRESHOLD_DAYS``: CRR Art. 111 OC short-maturity day
  boundary (365); the engine maps OC to the 20% MLR CCF at/below it.

References:
    - CRR Art. 111: SA CCF categories (Annex I product bands)
    - CRR Annex I paras 1-4: OBS product -> risk band mapping
    - PRA PS1/26 Art. 111 Table A1: Basel 3.1 SA CCF schedule
"""

from __future__ import annotations

import polars as pl
from watchfire import cites

from rwa_calc.data.schemas import OBS_PRODUCT_SYNONYMS

# =============================================================================
# ANNEX I PRODUCT -> RISK_TYPE MAPPING (CRR Annex I paras 1-4 / Art. 111(1))
# =============================================================================

# Maps a normalised concrete OBS *product* key to its abstract Annex I
# ``risk_type`` bucket. Framework-INVARIANT: every product in scope resolves to
# the same risk_type under both CRR and PRA PS1/26 Table A1; the framework split
# lives only downstream in the rulepack ``sa_ccf`` lookup. Keyed by the uppercase
# values produced by ``data.schemas.OBS_PRODUCT_SYNONYMS``.
#
# - ACCEPTANCE -> FR (CRR Annex I para 1 / Table A1 Row 1): bankers' acceptances
#   are direct credit substitutes -> 100% CCF.
# - PERFORMANCE_BOND / WARRANTY / TENDER_BOND / BID_BOND -> MLR (CRR Annex I
#   Row 6(b) / Table A1 Row 6(b)): non-direct-credit-substitute guarantees -> 20%.
# - DOCUMENTARY_CREDIT / TRADE_LC -> MLR (CRR Annex I Row 6(a) / Table A1
#   Row 6(a)): self-liquidating trade-related letters of credit -> 20%.
ANNEX1_PRODUCT_RISK_TYPE: dict[str, str] = {
    "ACCEPTANCE": "FR",
    "PERFORMANCE_BOND": "MLR",
    "WARRANTY": "MLR",
    "TENDER_BOND": "MLR",
    "BID_BOND": "MLR",
    "DOCUMENTARY_CREDIT": "MLR",
    "TRADE_LC": "MLR",
}

# CRR Art. 111: "other commitments" mapped to MLR (20%) when remaining maturity
# <= 1 year. The day threshold is a structural int day count; the 20% CCF itself
# lives in the rulepack (``oc_short_maturity_ccf`` in packs/common.py).
OC_SHORT_MATURITY_THRESHOLD_DAYS: int = 365


# CRR Annex I product bands are given regulatory effect by Art. 111(1); the
# watchfire parser only accepts an article-based citation, so the Annex I mapping
# is attributed to Art. 111.
@cites("CRR Art. 111")
def build_product_to_risk_type_expr(
    product_col: str = "obs_product",
) -> pl.Expr:
    """Build a Polars expression mapping a concrete OBS product to its risk_type.

    Resolves the abstract Annex I ``risk_type`` bucket (FR / MLR / ...) from a
    normalised concrete product key via ``ANNEX1_PRODUCT_RISK_TYPE``. The mapping
    is framework-invariant (CRR Annex I == PRA PS1/26 Table A1 for every product
    in scope). Unknown / unmapped products and nulls produce a null result, so
    the caller can leave the existing ``risk_type`` resolution untouched.

    Args:
        product_col: Name of the obs_product column on the frame.

    Returns:
        String Polars expression evaluating to the resolved risk_type (or null
        when the product is null / unmapped).
    """
    casted = pl.col(product_col).cast(pl.Utf8, strict=False).fill_null("")
    lowered = casted.str.to_lowercase()
    canonical = lowered.replace_strict(OBS_PRODUCT_SYNONYMS, default=casted.str.to_uppercase())
    return canonical.replace_strict(
        ANNEX1_PRODUCT_RISK_TYPE,
        default=pl.lit(None, dtype=pl.Utf8),
    )
