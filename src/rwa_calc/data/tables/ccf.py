"""
Credit Conversion Factor (CCF) tables — CRR Art. 111 / 166 and PRA PS1/26 Table A1.

Canonical home for the SA and F-IRB CCF percentages used by
``engine/ccf.py`` to convert off-balance-sheet nominal amounts into
credit-equivalent EAD. Framework selection happens at the call site via
``CalculationConfig`` or the ``is_basel_3_1`` flag on the builder
helpers — there is exactly one source of truth for every regulatory
scalar in this domain.

Tables (canonical dicts, keyed by the uppercase values in
``data.schemas.VALID_RISK_TYPES_INPUT``):

- ``SA_CCF_CRR``: CRR Art. 111 SA mapping (FR/FRC=100%, MR=50%,
  MR_ISSUED=50% (Annex I Row 3 issued OBS items), OC=50%, MLR=20%,
  LR=0%). The OC=50% value is the conservative
  default; ``engine.ccf._compute_ccf`` overrides it to 20% when
  remaining maturity ≤ ``OC_SHORT_MATURITY_THRESHOLD_DAYS`` per
  Art. 111 (OC mapped to MLR for short maturities).
- ``SA_CCF_B31``: PRA PS1/26 Art. 111 Table A1 overrides — OC=40%
  (Row 5) and LR/UCC=10% (Row 6); other rows reuse CRR values.
- ``FIRB_OBS_FALLBACK``: CRR Art. 166(10) issued-OBS fallback
  mapping (FR=100%, MR/OC=50%, MLR=20%, LR=0%).

Module-level constants:

- ``FIRB_TRADE_LC_CCF``: Art. 166(8)(b) short-term trade LC carve-out
- ``FIRB_CREDIT_LINE_CCF``: Art. 166(8)(d) credit lines / NIFs / RUFs
- ``SA_CCF_DEFAULT``: MR-equivalent unrecognised fallback
- ``OC_SHORT_MATURITY_CCF`` / ``OC_SHORT_MATURITY_THRESHOLD_DAYS``:
  CRR Art. 111 OC short-maturity override

Builder functions return Polars expressions that consume a risk_type
column and produce a Float64 CCF column. Decimal → float conversion
happens in the builder; the source-of-truth tables stay Decimal.

References:
    - CRR Art. 111: SA CCF categories (FR / MR / MLR / LR)
    - CRR Art. 166(8): F-IRB bespoke CCFs (UCC, trade LCs, credit lines)
    - CRR Art. 166(10): F-IRB residual fallback for issued OBS items
    - PRA PS1/26 Art. 111 Table A1: Basel 3.1 SA CCF schedule
    - PRA PS1/26 Art. 166C: Basel 3.1 F-IRB uses SA CCFs
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl
from watchfire import cites

from rwa_calc.data.schemas import RISK_TYPE_SYNONYMS

# =============================================================================
# SA CCF TABLES (CRR Art. 111 / PRA PS1/26 Art. 111 Table A1)
# =============================================================================

# CRR Art. 111 SA CCFs. OC=0.50 is the >1yr conservative default; the
# engine overrides to OC_SHORT_MATURITY_CCF when remaining maturity
# ≤ OC_SHORT_MATURITY_THRESHOLD_DAYS.
SA_CCF_CRR: dict[str, Decimal] = {
    "FR": Decimal("1.00"),
    "FRC": Decimal("1.00"),
    "MR": Decimal("0.50"),
    # CRR Annex I Row 3 — "other" issued medium-risk OBS items. Same 50% SA
    # CCF as Row 4 (MR) but routed via a distinct risk_type so issued
    # contingents are separable from NIF/RUF commitments (P2.30).
    "MR_ISSUED": Decimal("0.50"),
    "OC": Decimal("0.50"),
    "MLR": Decimal("0.20"),
    "LR": Decimal("0.00"),
}

# PRA PS1/26 Art. 111 Table A1: OC=0.40 (Row 5 — new category),
# LR/UCC=0.10 (Row 6). FR/FRC/MR/MLR unchanged from CRR.
SA_CCF_B31: dict[str, Decimal] = {
    "FR": Decimal("1.00"),
    "FRC": Decimal("1.00"),
    "MR": Decimal("0.50"),
    # CRR Annex I Row 3 issued medium-risk OBS items mirror MR (50%) under
    # Basel 3.1 Table A1 as well (P2.30).
    "MR_ISSUED": Decimal("0.50"),
    "OC": Decimal("0.40"),
    "MLR": Decimal("0.20"),
    "LR": Decimal("0.10"),
}

# CRR Art. 166(10) F-IRB residual fallback for issued OBS items not in
# scope of Art. 166(8). Selected by the engine when
# ``is_obs_commitment=False``.
FIRB_OBS_FALLBACK: dict[str, Decimal] = {
    "FR": Decimal("1.00"),
    "FRC": Decimal("1.00"),
    "MR": Decimal("0.50"),
    # CRR Annex I Row 3 issued OBS items resolve to the same Art. 166(10)(b)
    # 50% medium-risk fallback as MR (P2.30).
    "MR_ISSUED": Decimal("0.50"),
    "OC": Decimal("0.50"),
    "MLR": Decimal("0.20"),
    "LR": Decimal("0.00"),
}

# Art. 166(8)(b): short-term trade LC arising from movement of goods.
FIRB_TRADE_LC_CCF: Decimal = Decimal("0.20")

# Art. 166(8)(d): credit lines / NIFs / RUFs (is_obs_commitment=True).
FIRB_CREDIT_LINE_CCF: Decimal = Decimal("0.75")

# Conservative MR-equivalent fallback for unrecognised risk_type values.
SA_CCF_DEFAULT: Decimal = Decimal("0.50")

# CRR Art. 111: "other commitments" mapped to MLR (20%) when remaining
# maturity ≤ 1 year. Both the CCF and the threshold are regulatory.
OC_SHORT_MATURITY_CCF: Decimal = Decimal("0.20")
OC_SHORT_MATURITY_THRESHOLD_DAYS: int = 365


# =============================================================================
# BUILDER HELPERS
# =============================================================================


def _normalize_risk_type(risk_type_col: str) -> pl.Expr:
    """Lowercase and canonicalise a risk_type column to the uppercase keys.

    Maps every spelling accepted on input (short code or full name) to
    its canonical uppercase form via RISK_TYPE_SYNONYMS. Unrecognised
    values pass through uppercased so the builders' ``otherwise()``
    branch picks them up. The cast to ``pl.Utf8`` accommodates frames
    where the column is null-typed (e.g. a literal ``[None]`` column).
    """
    casted = pl.col(risk_type_col).cast(pl.Utf8, strict=False).fill_null("")
    lowered = casted.str.to_lowercase()
    return lowered.replace_strict(RISK_TYPE_SYNONYMS, default=casted.str.to_uppercase())


@cites("CRR Art. 111")
def build_sa_ccf_expr(
    risk_type_col: str = "risk_type",
    is_basel_3_1: bool = False,
) -> pl.Expr:
    """Build a Polars expression that maps risk_type to SA CCFs.

    Args:
        risk_type_col: Name of the risk_type column on the frame.
        is_basel_3_1: Select PRA PS1/26 Table A1 when True, CRR Art. 111
            when False.

    Returns:
        Float64 Polars expression evaluating to the SA CCF.
    """
    table = SA_CCF_B31 if is_basel_3_1 else SA_CCF_CRR
    canonical = _normalize_risk_type(risk_type_col)
    return (
        pl.when(canonical == "FR")
        .then(pl.lit(float(table["FR"])))
        .when(canonical == "FRC")
        .then(pl.lit(float(table["FRC"])))
        .when(canonical == "MR")
        .then(pl.lit(float(table["MR"])))
        # CRR Annex I Row 3 issued medium-risk OBS items — explicit 50%
        # (mirrors MR / Row 4) so EAD is provably equal, not a default fallback.
        .when(canonical == "MR_ISSUED")
        .then(pl.lit(float(table["MR_ISSUED"])))
        .when(canonical == "OC")
        .then(pl.lit(float(table["OC"])))
        .when(canonical == "MLR")
        .then(pl.lit(float(table["MLR"])))
        .when(canonical == "LR")
        .then(pl.lit(float(table["LR"])))
        .otherwise(pl.lit(float(SA_CCF_DEFAULT)))
    )


@cites("CRR Art. 166")
def build_firb_ccf_expr(risk_type_col: str = "risk_type") -> pl.Expr:
    """Build a Polars expression for CRR F-IRB CCFs (Art. 166(8) + (10)).

    Implements both F-IRB CCF clauses of CRR Article 166:

    Art. 166(8) bespoke CCFs (selected when ``is_obs_commitment=True``
    and matching the listed commitment type):
        (a) UCC credit lines (LR risk_type) -> 0%
        (b) Short-term trade LCs (MLR + is_short_term_trade_lc) -> 20%
        (d) Other credit lines / NIFs / RUFs (MR/MLR/OC commitments) -> 75%

    Art. 166(10) residual fallback (selected when
    ``is_obs_commitment=False``):
        (a) Full risk -> 100%; (b) Medium-risk -> 50%;
        (c) Medium/low-risk -> 20%; (d) Low-risk -> 0%.

    FR/FRC and LR converge to the same value under either path, so they
    are handled before the commitment/issued split. The Art. 166(8)(b)
    trade-LC carve-out wins over the issued/commitment split.

    Args:
        risk_type_col: Name of the risk_type column on the frame.

    Returns:
        Float64 Polars expression evaluating to the F-IRB CCF.
    """
    canonical = _normalize_risk_type(risk_type_col)
    is_commitment = pl.col("is_obs_commitment").fill_null(True)
    is_trade_lc = pl.col("is_short_term_trade_lc").fill_null(False)
    is_mlr = canonical == "MLR"
    # MR_ISSUED (CRR Annex I Row 3 issued OBS items) mirrors MR exactly: it
    # rides the same Art. 166(8)(d) commitment / Art. 166(10)(b) issued split,
    # so it never diverges to the otherwise default (P2.30).
    is_mr_or_oc = canonical.is_in(["MR", "MR_ISSUED", "OC"])
    return (
        # FR/FRC -> 100% under both Art. 166(8) general and Art. 166(10)(a)
        pl.when(canonical.is_in(["FR", "FRC"]))
        .then(pl.lit(float(FIRB_OBS_FALLBACK["FR"])))
        # LR -> 0% under both Art. 166(8)(a) and Art. 166(10)(d)
        .when(canonical == "LR")
        .then(pl.lit(float(FIRB_OBS_FALLBACK["LR"])))
        # Art. 166(8)(b): short-term trade LC carve-out wins over both buckets
        .when(is_mlr & is_trade_lc)
        .then(pl.lit(float(FIRB_TRADE_LC_CCF)))
        # Art. 166(8)(d): credit lines / NIFs / RUFs -> 75%
        .when(is_commitment & (is_mr_or_oc | is_mlr))
        .then(pl.lit(float(FIRB_CREDIT_LINE_CCF)))
        # Art. 166(10)(b): MR / OC issued items -> 50%
        .when(is_mr_or_oc)
        .then(pl.lit(float(FIRB_OBS_FALLBACK["MR"])))
        # Art. 166(10)(c): MLR issued items -> 20%
        .when(is_mlr)
        .then(pl.lit(float(FIRB_OBS_FALLBACK["MLR"])))
        # Conservative MR-equivalent fallback for unrecognised risk_type values
        .otherwise(pl.lit(float(SA_CCF_DEFAULT)))
    )
