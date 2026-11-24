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
- Art. 166D(1)(a): Own-estimate CCFs permitted ONLY for revolving loan COMMITMENTS
  (``is_revolving`` and ``is_obs_commitment``) — an issued item under a revolving
  facility is not a commitment and takes the SA factor (Art. 166D(1)(b))
- Non-revolving A-IRB must use SA CCFs from Table A1
- Revolving facilities with 100% SA CCF (Table A1 Row 2) cannot use own-estimates
- All own-estimate CCFs floored at 50% of SA CCF (CRE32.27)
- Art. 166D(3)/(4): the single own estimate of EAD (``ead_modelled``) reaches the
  same revolving loan commitments only (never an issued item, a non-revolving
  commitment or an Art. 166A(5) purchased-receivables commitment)
- Art. 166D(5): Three EAD floor tests for A-IRB:
  (a) CCF floor = 50% x SA CCF (implemented in _compute_ccf)
  (b) Facility-level EAD floor = on-BS EAD + 50% x F-IRB off-BS EAD (Art. 166D(3))
  (c) Fully-drawn EAD floor = on-BS EAD ignoring Art. 166D (Art. 166D(4))

PS1/26 Art. 166A(5) (IRB only): a revolving purchased-receivables undrawn purchase
commitment takes a fixed 40% (10% if unconditionally cancellable) on F-IRB, slotting
and A-IRB; the SA keeps its Table A1 bucket.

PS1/26 Table A1 Row 4(b): a UK residential mortgage commitment takes 50%; the flag is
tri-state and, when unstated, derived from the row's evidence (Basel 3.1 only).

The ``obs_product`` -> risk_type map is regime-specific (CRR Annex I vs Table A1) and
is read from the resolved pack.

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

from collections.abc import Hashable, Mapping
from datetime import date
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.data.schemas import OBS_PRODUCT_SYNONYMS, RISK_TYPE_SYNONYMS
from rwa_calc.domain.enums import ApproachType, ExposureClass
from rwa_calc.engine.eu_sovereign import denomination_currency_expr
from rwa_calc.rulebook import RulepackV0
from rwa_calc.rulebook.compile import lookup_float_map, scalar_value
from rwa_calc.rulebook.resolve import resolve

if TYPE_CHECKING:
    from rwa_calc.contracts.config import CalculationConfig
    from rwa_calc.rulebook.resolve import ResolvedRulepack

# SA / F-IRB CCF schedules resolved from the rulepack once at module load
# (mirrors the comparison.py / slotting module-level pattern). The Decimal ->
# float boundary is lookup_float_map / scalar_value, matching the historical
# float(Decimal(...)) conversion in the retired data/tables/ccf.py builders.
_CRR_PACK = resolve("crr", date(2026, 1, 1))
_B31_PACK = resolve("b31", date(2027, 1, 1))
_SA_CCF_CRR_MAP = lookup_float_map(_CRR_PACK.lookup("sa_ccf"))
_SA_CCF_B31_MAP = lookup_float_map(_B31_PACK.lookup("sa_ccf"))
_FIRB_OBS_FALLBACK_MAP = lookup_float_map(_CRR_PACK.lookup("firb_obs_fallback_ccf"))
_FIRB_TRADE_LC_CCF = scalar_value(_CRR_PACK.scalar_param("firb_trade_lc_ccf"))
_FIRB_CREDIT_LINE_CCF = scalar_value(_CRR_PACK.scalar_param("firb_credit_line_ccf"))
_OC_SHORT_MATURITY_CCF = scalar_value(_CRR_PACK.scalar_param("oc_short_maturity_ccf"))
# CRR Art. 111(1) / Annex I items 2(b),3(b): "other commitments" remap to the 20%
# MLR CCF at/below this ORIGINAL-maturity day boundary (365 days = 1yr); above it
# the 50% MR CCF applies. The split keys on ORIGINAL, not residual, maturity —
# sourced via IntParam (S13-c).
_OC_SHORT_MATURITY_THRESHOLD_DAYS = _CRR_PACK.int_param("oc_short_maturity_threshold_days").value


def _normalize_risk_type(risk_type_col: str) -> pl.Expr:
    """Lowercase and canonicalise a risk_type column to the uppercase keys.

    Maps every spelling accepted on input (short code or full name) to its
    canonical uppercase form via RISK_TYPE_SYNONYMS. Unrecognised values pass
    through uppercased so the consumers' ``otherwise()`` branch picks them up.
    The cast to ``pl.Utf8`` accommodates frames where the column is null-typed.
    """
    casted = pl.col(risk_type_col).cast(pl.Utf8, strict=False).fill_null("")
    lowered = casted.str.to_lowercase()
    return lowered.replace_strict(RISK_TYPE_SYNONYMS, default=casted.str.to_uppercase())


# CRR Annex I product bands are given regulatory effect by Art. 111(1); the
# watchfire parser only accepts an article-based citation, so the Annex I mapping
# is attributed to Art. 111 (PS1/26 Table A1 is the same article's Column A).
@cites("CRR Art. 111")
@cites("PS1/26, paragraph 111")
def build_product_to_risk_type_expr(
    product_map: Mapping[str, str],
    product_col: str = "obs_product",
) -> pl.Expr:
    """Build a Polars expression mapping a concrete OBS product to its risk_type.

    Resolves the ``risk_type`` bucket (FR / MR_ISSUED / MLR / ...) from a
    normalised concrete product key via ``product_map`` — the RESOLVED pack's
    ``obs_product_to_risk_type`` CategoryMap. The map is regime-specific (CM-07):
    CRR Annex I 2(a) / 2(b)(i) put plain documentary credits and shipping /
    customs / tax bonds in medium risk (50%) where PS1/26 Table A1 row 6 gives
    them 20%, so the caller passes the map of the regime it is computing.
    Unknown / unmapped products and nulls produce a null result, so the caller
    can leave the existing ``risk_type`` resolution untouched.

    Args:
        product_map: Canonical product key -> risk_type bucket, from the pack.
        product_col: Name of the obs_product column on the frame.

    Returns:
        String Polars expression evaluating to the resolved risk_type (or null
        when the product is null / unmapped).
    """
    casted = pl.col(product_col).cast(pl.Utf8, strict=False).fill_null("")
    lowered = casted.str.to_lowercase()
    canonical = lowered.replace_strict(OBS_PRODUCT_SYNONYMS, default=casted.str.to_uppercase())
    return canonical.replace_strict(
        dict(product_map),
        default=pl.lit(None, dtype=pl.Utf8),
    )


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
    *,
    commitment_col: str | None = None,
) -> pl.Expr:
    """Polars expression mapping risk_type to SA CCFs.

    CRR Art. 111 (Annex I categories) when ``is_basel_3_1`` is False, PRA
    PS1/26 Table A1 when True. The CCF values come from the rulepack
    (``sa_ccf`` lookup).

    **The residual limb is regime-divergent** (P1.267). An unrecognised or
    absent ``risk_type`` does NOT take a shared 50% fallback — the two regimes
    write their residuals as different provisions with different values:

    - **CRR Annex I item 1(k)** — "other items also carrying full risk" — is
      the only residual available unconditionally. Items 2(b)(iv), 3(b)(ii)
      and 4(c) each read "other items also carrying ... risk **and as
      communicated to** [the competent authority]". An item the engine cannot
      classify has by definition not been notified, so it cannot lawfully sit
      in the 50% bucket. The residual is 100% as a matter of the text, not of
      prudence.
    - **PS1/26 Table A1** has three residual limbs and none carries a
      notification condition. Row 3 ("other issued off-balance sheet items
      that do **not** have the character of credit substitutes") is 50%; Row 5
      ("any other commitment not subject to a conversion factor of 10%, 50% or
      100%") is 40%. So the B31 residual splits on ``is_obs_commitment``, and
      an unclassifiable *issued* item at 50% is RIGHT BY THE TEXT rather than
      a fallback.

    This is the Art. 120 trap — two regimes, genuinely different texts, one
    shared implementation — and harmonising the two arms would be wrong under
    PS1/26 in two places, in opposite directions.

    Args:
        risk_type_col: Name of the risk_type column.
        is_basel_3_1: Whether PS1/26 Table A1 applies (else CRR Annex I).
        commitment_col: Boolean column separating Table A1 Row 5 (commitment)
            from Row 3 (issued item). Ignored under CRR — item 1(k) has no
            commitment/issued split.

            Defaults to ``None``, which selects Row 3 outright and references
            no column. That default is deliberate and load-bearing: naming a
            column here puts it in the EXPRESSION'S FOOTPRINT, and some
            callers apply this expression to projected frames that carry
            ``risk_type`` and nothing else (the provisions weighting basis).
            Defaulting to the column raised ``ColumnNotFoundError`` there, and
            in the MOF waterfall before it projected the umbrella's flag.
            Callers that hold the flag — ``_compute_ccf``, and the waterfall's
            ranking, which must rank on the factor the row is priced at
            (P1.452) — opt in explicitly.
    """
    table = _SA_CCF_B31_MAP if is_basel_3_1 else _SA_CCF_CRR_MAP
    canonical = _normalize_risk_type(risk_type_col)
    return (
        pl.when(canonical == "FR")
        .then(pl.lit(table["FR"]))
        .when(canonical == "FRC")
        .then(pl.lit(table["FRC"]))
        .when(canonical == "MR")
        .then(pl.lit(table["MR"]))
        # CRR Annex I Row 3 issued medium-risk OBS items — explicit 50%
        # (mirrors MR / Row 4) so EAD is provably equal, not a default fallback.
        .when(canonical == "MR_ISSUED")
        .then(pl.lit(table["MR_ISSUED"]))
        .when(canonical == "OC")
        .then(pl.lit(table["OC"]))
        .when(canonical == "MLR")
        .then(pl.lit(table["MLR"]))
        .when(canonical == "LR")
        .then(pl.lit(table["LR"]))
        .otherwise(_sa_ccf_residual(table, is_basel_3_1, commitment_col))
    )


def _sa_ccf_residual(
    table: Mapping[Hashable, float], is_basel_3_1: bool, commitment_col: str | None
) -> pl.Expr:
    """Residual CCF for a risk_type the Annex I / Table A1 ladder does not name.

    See :func:`sa_ccf_expression` for the textual argument. Deliberately not a
    shared "default": the retired ``sa_ccf_default`` pack scalar encoded the
    residual as regime-invariant, which is what P1.267 refuted.
    """
    if not is_basel_3_1:
        # CRR Annex I item 1(k) — the only residual with no notification condition.
        return pl.lit(table["FR"])
    if commitment_col is None:
        return pl.lit(table["MR_ISSUED"])
    # PS1/26 Table A1 Row 5 (commitment, 40%) vs Row 3 (issued, 50%). A null
    # flag leaves the row undecidable between the two, and ``pl.when(null)``
    # takes the ``otherwise`` branch — so it lands on the HIGHER Row 3 limb
    # with no ``fill_null`` needed. Deliberately unlike _firb_ccf_for_col's
    # fill_null(True): there True selects the correct Art. 166(8) ladder for a
    # facility's undrawn limb, here it would pick the lower of two values on no
    # evidence.
    return (
        pl.when(pl.col(commitment_col))
        .then(pl.lit(table["OC"]))
        .otherwise(pl.lit(table["MR_ISSUED"]))
    )


@cites("PS1/26, paragraph 111")
def commitment_to_issue_ccf_expression(
    ccf: pl.Expr, underlying_risk_type_col: str = "underlying_risk_type"
) -> pl.Expr:
    """Cap ``ccf`` at the Table A1 factor of the item a commitment is to issue.

    PS1/26 Art. 111(1)(c): "a commitment to issue an off-balance sheet item
    listed in Table A1 shall be calculated ... using the lower of: (i) the
    percentage specified in Column B that is applicable to the off-balance sheet
    item on which the commitment is made; and (ii) the percentage specified in
    Column B that is applicable to the type of commitment". A null or blank
    ``underlying_risk_type`` means the row is not a commitment to issue, and
    ``ccf`` is returned unchanged.

    The underlying is the item to BE ISSUED, so its residual is Table A1 Row 3
    by construction (no ``commitment_col``); the outer row's
    ``is_obs_commitment`` describes the commitment and would be the wrong flag.

    Basel-3.1-only: CRR Art. 111(1) has no lower-of (P1.265), so callers gate
    this on the ``firb_uses_sa_ccf`` pack Feature. Shared by the CCF stage and
    the MOF waterfall's ranking (P1.452) so the two cannot price a sub-limit
    differently.

    Args:
        ccf: The conversion factor the row's own bucket gives it.
        underlying_risk_type_col: Column holding the underlying item's bucket.
    """
    has_underlying = pl.col(underlying_risk_type_col).fill_null("").str.len_chars() > 0
    underlying_sa = sa_ccf_expression(underlying_risk_type_col, is_basel_3_1=True)
    return pl.when(has_underlying).then(pl.min_horizontal(ccf, underlying_sa)).otherwise(ccf)


@cites("PS1/26, paragraph 111")
def uk_residential_mortgage_ccf_expression(ccf: pl.Expr, is_resi_commitment: pl.Expr) -> pl.Expr:
    """Move ``ccf`` to the Table A1 Row 4(b) 50% for a UK residential mortgage commitment.

    PRA PS1/26 Art. 111(1) Table A1 Row 4(b): "UK residential mortgage
    commitments that are not subject to a conversion factor of 10% or 100%"
    attract 50%. A row whose ``ccf`` is already 10% (Row 7 UCC) or 100% (Rows
    1 / 2) sits in the carve-out and keeps it; a null ``is_resi_commitment``
    takes the ``otherwise`` branch, so an unevidenced row keeps its bucket.

    Basel-3.1-only: callers gate this on the ``firb_uses_sa_ccf`` pack Feature.
    Shared by the CCF stage (both carriers) and the MOF waterfall's ranking.

    Args:
        ccf: The conversion factor the row would otherwise take.
        is_resi_commitment: Boolean expression - the row is a Row 4(b) commitment.
    """
    row_4b_ccf = _SA_CCF_B31_MAP["MR"]
    carve_out_ccfs = (_SA_CCF_B31_MAP["LR"], _SA_CCF_B31_MAP["FR"])
    return (
        pl.when(is_resi_commitment & ~ccf.is_in(carve_out_ccfs))
        .then(pl.lit(row_4b_ccf))
        .otherwise(ccf)
    )


@cites("CRR Art. 111(1)")
def oc_original_maturity_ccf_expression(
    ccf: pl.Expr, original_maturity_days: pl.Expr, risk_type_col: str = "risk_type"
) -> pl.Expr:
    """Remap an ``OC`` ("other commitments") ``ccf`` to 20% on a short ORIGINAL maturity (CRR).

    CRR Annex I items 2(b)(ii) / 3(b)(i) split undrawn credit facilities on
    their original maturity: 50% (medium risk) above one year, 20% (medium/low
    risk) at or below it. ``sa_ccf_expression`` supplies the 50% default; this
    drops it to ``oc_short_maturity_ccf`` where ``original_maturity_days`` is at
    or below ``oc_short_maturity_threshold_days``. A null maturity keeps
    ``ccf``. CRR-only: callers gate it on the ``firb_uses_sa_ccf`` Feature being
    off. Shared by the CCF stage and the MOF waterfall's ranking.

    Args:
        ccf: The conversion factor from the row's bucket.
        original_maturity_days: The row's original maturity in days, or null.
        risk_type_col: Column holding the row's bucket.
    """
    normalized_rt = pl.col(risk_type_col).fill_null("").str.to_lowercase()
    is_oc = normalized_rt.is_in(["oc", "other_commit"])
    is_short_original = original_maturity_days <= _OC_SHORT_MATURITY_THRESHOLD_DAYS
    return pl.when(is_oc & is_short_original).then(pl.lit(_OC_SHORT_MATURITY_CCF)).otherwise(ccf)


def original_maturity_days_expression(
    value_date_col: str = "value_date", maturity_date_col: str = "maturity_date"
) -> pl.Expr:
    """Original maturity in days from a start and a maturity date; null if either is null."""
    return (
        (pl.col(maturity_date_col).cast(pl.Date) - pl.col(value_date_col).cast(pl.Date))
        .dt.total_days()
        .cast(pl.Float64)
    )


@cites("CRR Art. 166")
def _firb_ccf_for_col(risk_type_col: str = "risk_type") -> pl.Expr:
    """Polars expression for CRR F-IRB CCFs (Art. 166(8) + (10)).

    Implements both F-IRB CCF clauses of CRR Article 166:

    Art. 166(8) bespoke CCFs (is_obs_commitment=True, matching commitment):
        (a) UCC credit lines (LR) -> 0%; (b) short-term trade LCs
        (MR_ISSUED / MLR + is_short_term_trade_lc) -> 20%; (d) other
        credit lines / NIFs / RUFs (MR/MLR/OC commitments) -> 75%.
    Art. 166(10) residual fallback (is_obs_commitment=False):
        (a) full risk -> 100%; (b) medium -> 50%; (c) medium/low -> 20%;
        (d) low -> 0%.

    FR/FRC and LR converge under either path; the Art. 166(8)(b) trade-LC
    carve-out wins over the issued/commitment split. Values come from the
    rulepack (``firb_obs_fallback_ccf`` lookup + the bespoke scalars).
    """
    canonical = _normalize_risk_type(risk_type_col)
    is_commitment = pl.col("is_obs_commitment").fill_null(True)
    is_trade_lc = pl.col("is_short_term_trade_lc").fill_null(False)
    is_mlr = canonical == "MLR"
    # MR_ISSUED (CRR Annex I Row 3 issued OBS items) mirrors MR exactly: it
    # rides the same Art. 166(8)(d) commitment / Art. 166(10)(b) issued split,
    # so it never diverges to the otherwise default (P2.30).
    is_mr_or_oc = canonical.is_in(["MR", "MR_ISSUED", "OC"])
    # Art. 166(8)(b) reaches "short-term letters of credit arising from the
    # movement of goods ... for both the issuing and confirming institutions"
    # whatever their Annex I category: a documentary credit not secured by its
    # shipment is Annex I 2(a) MEDIUM risk (the CRR ``obs_product`` map books it
    # MR_ISSUED, the issued-item medium-risk bucket), and it keeps the 20% when
    # flagged as a short-term trade LC (TR-04). MR (NIF / RUF commitments) and
    # OC (other commitments) are commitment buckets, never a letter of credit,
    # so they stay on Art. 166(8)(d) even when the trade flag is set.
    is_trade_lc_bucket = canonical.is_in(["MR_ISSUED", "MLR"])
    return (
        # FR/FRC -> 100% under both Art. 166(8) general and Art. 166(10)(a)
        pl.when(canonical.is_in(["FR", "FRC"]))
        .then(pl.lit(_FIRB_OBS_FALLBACK_MAP["FR"]))
        # LR -> 0% under both Art. 166(8)(a) and Art. 166(10)(d)
        .when(canonical == "LR")
        .then(pl.lit(_FIRB_OBS_FALLBACK_MAP["LR"]))
        # Art. 166(8)(b): short-term trade LC carve-out wins over both buckets
        .when(is_trade_lc_bucket & is_trade_lc)
        .then(pl.lit(_FIRB_TRADE_LC_CCF))
        # Art. 166(8)(d): credit lines / NIFs / RUFs -> 75%
        .when(is_commitment & (is_mr_or_oc | is_mlr))
        .then(pl.lit(_FIRB_CREDIT_LINE_CCF))
        # Art. 166(10)(b): MR / OC issued items -> 50%
        .when(is_mr_or_oc)
        .then(pl.lit(_FIRB_OBS_FALLBACK_MAP["MR"]))
        # Art. 166(10)(c): MLR issued items -> 20%
        .when(is_mlr)
        .then(pl.lit(_FIRB_OBS_FALLBACK_MAP["MLR"]))
        # Art. 166(10)(a): an unrecognised risk_type has no Annex I category, so
        # it takes item 1(k) ("other items also carrying full risk") — the only
        # residual with no supervisory-notification condition — and 1(k) routes
        # to the full-risk limb of Art. 166(10). Was the shared 50%
        # ``sa_ccf_default``, which asserted a medium-risk category the item
        # could not have been notified into (P1.267).
        .otherwise(pl.lit(_FIRB_OBS_FALLBACK_MAP["FR"]))
    )


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
    - Own-estimate CCFs ONLY for revolving loan commitments with SA CCF < 100%
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
        *,
        pack: ResolvedRulepack | None = None,
    ) -> pl.LazyFrame:
        """
        Apply CCF to calculate EAD for off-balance sheet exposures.

        CCF determination follows CRR Art. 111 categories based on risk_type:
        - SA: FR=100%, MR=50%, MLR=20%, LR=0%
        - F-IRB Art. 166(8)(d): MR/MLR/OC commitments (credit lines / NIFs / RUFs)
          when ``is_obs_commitment=True`` -> 75%
        - F-IRB Art. 166(10) fallback: issued OBS items (``is_obs_commitment=False``)
          -> 100% FR / 50% MR / 20% MLR / 0% LR
        - F-IRB Art. 166(8)(b): MLR / MR_ISSUED with ``is_short_term_trade_lc`` -> 20%
        - A-IRB CRR: Uses ccf_modelled if provided, otherwise falls back to SA
        - A-IRB B31: Own CCF only for revolving loan commitments (non-100% SA);
          else SA CCF (Art. 166D); Art. 166A(5) purchased receivables fixed
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
        # The exposure's own (pre-FX) denomination: the FX stage overwrites
        # ``currency`` with the reporting currency (RE-14 UK evidence).
        denomination_ccy = denomination_currency_expr(names)
        exposures = self._compute_ccf(
            exposures, config, pack=pack, denomination_ccy=denomination_ccy
        )
        exposures = self._compute_ead(exposures, has_provision_cols, config, pack=pack)
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
            # PRA PS1/26 Art. 111(1) Table A1 Row 4(b): a tri-state flag (null =
            # not stated, derived under Basel 3.1 from the evidence columns
            # below — RE-14). Absent means not stated; with the evidence columns
            # also absent the derivation is null and the override a no-op.
            (
                "is_uk_residential_mortgage_commitment",
                pl.lit(None).cast(pl.Boolean).alias("is_uk_residential_mortgage_commitment"),
            ),
            # Row 4(b) derivation evidence (RE-14). Always present on the
            # pipeline's CRM entry edge; null when callers (e.g. unit tests)
            # construct exposures without them, which derives nothing.
            ("exposure_class", pl.lit(None).cast(pl.String).alias("exposure_class")),
            (
                "residential_collateral_value",
                pl.lit(None).cast(pl.Float64).alias("residential_collateral_value"),
            ),
            ("property_type", pl.lit(None).cast(pl.String).alias("property_type")),
            ("cp_country_code", pl.lit(None).cast(pl.String).alias("cp_country_code")),
            ("currency", pl.lit(None).cast(pl.String).alias("currency")),
            # PRA PS1/26 Art. 166A(5): default False so the revolving
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
        *,
        pack: ResolvedRulepack | None = None,
        denomination_ccy: pl.Expr,
    ) -> pl.LazyFrame:
        """Compute CCF based on risk type and approach.

        Determines SA and F-IRB CCFs from risk_type, then selects the final CCF
        based on the exposure's approach (SA/F-IRB/A-IRB).

        CRR Annex I / PS1/26 Table A1 obs_product fill: before resolving CCFs, any
        row whose ``risk_type`` is null/empty has its ``risk_type`` resolved from
        the concrete ``obs_product`` key via the resolved pack's
        ``obs_product_to_risk_type`` map — regime-specific, since Annex I and
        Table A1 classify documentary credits and shipping / customs / tax bonds
        differently (CM-07). An explicit ``risk_type`` always wins — the fill is
        gated on the existing value being null/empty.

        Applies the PRA PS1/26 Art. 111(1) Table A1 Row 4(b) override: a UK
        residential-property commitment (``is_uk_residential_mortgage_commitment``)
        gets a 50% CCF under Basel 3.1 — on the SA and the F-IRB / Slotting
        carrier alike (Art. 166C(1)) — except where the otherwise-resolved CCF is
        10% (Row 7 UCC) or 100% (Row 1/2) — the Row 4(b) carve-out.

        References:
        - CRR Art. 111(1) / Annex I: SA CCF buckets.
        - CRR Art. 166(8)(a)-(d): F-IRB bespoke supervisory CCFs.
        - CRR Art. 166(8): own-estimate (modelled) A-IRB CCFs are admissible
          only within the Art. 166(8)(a)-(d) product scope.
        - CRR Art. 166(10): residual supervisory fallback for issued OBS items
          outside the Art. 166(8) scope.
        - PS1/26 Art. 166A(5): the fixed IRB purchased-receivables commitment CCF.
        - PS1/26 Art. 166D(1): A-IRB own estimates only for revolving loan
          commitments; every other item takes the SA factor.
        """
        resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack

        # CRR Annex I / PS1/26 Table A1: resolve risk_type from the concrete OBS
        # product when (and only when) no explicit risk_type was supplied, using
        # the regime's own map. Explicit risk_type always wins; an unmapped/null
        # product yields null and leaves risk_type unchanged.
        risk_type_is_blank = (
            pl.col("risk_type").cast(pl.Utf8, strict=False).fill_null("").str.len_chars() == 0
        )
        product_risk_type = build_product_to_risk_type_expr(
            resolved_pack.category_map("obs_product_to_risk_type").entries
        )
        exposures = exposures.with_columns(
            pl.when(risk_type_is_blank & product_risk_type.is_not_null())
            .then(product_risk_type)
            .otherwise(pl.col("risk_type"))
            .alias("risk_type"),
        )

        # S9c: the F-IRB-uses-SA-CCF routing gate (Art. 166C) reads the cited pack
        # Feature; sa_ccf_expression / _firb_ccf_for_col keep their is_basel_3_1 bool
        # plumbing params (Option B). All CCF VALUES stay static data-layer tables.
        is_b31 = resolved_pack.feature("firb_uses_sa_ccf")

        if is_b31:
            # Basel 3.1 Art. 166C: F-IRB uses SA CCFs (PRA PS1/26 Art. 111 Table A1)
            # FR=100%, MR=50%, MLR=20%, LR(UCC)=10%
            firb_ccf = sa_ccf_expression(is_basel_3_1=True, commitment_col="is_obs_commitment")
        else:
            # CRR F-IRB: Art. 166(8)(d) -> 75% for credit lines / NIFs / RUFs
            # (is_obs_commitment=True); Art. 166(10) -> 100/50/20/0% fallback for
            # issued OBS items not in scope of paragraphs 1-8.
            firb_ccf = _firb_ccf_for_col("risk_type")

        exposures = exposures.with_columns(
            sa_ccf_expression(is_basel_3_1=is_b31, commitment_col="is_obs_commitment").alias(
                "_sa_ccf_from_risk_type"
            ),
            firb_ccf.alias("_firb_ccf_from_risk_type"),
            (pl.col("nominal_amount").cast(pl.Float64, strict=False).abs() < 1e-10).alias(
                "_nominal_is_zero"
            ),
        )

        # CRR maturity-dependent OC override (Art. 111(1) / Annex I items 2(b),
        # 3(b)): "other commitments" attract the MR 50% CCF when their ORIGINAL
        # maturity is > 1yr (item 2(b)) and the MLR 20% CCF when it is <= 1yr
        # (item 3(b)). The split keys on ORIGINAL maturity, not residual: the
        # explicit ``original_maturity_years`` when present, else the
        # (maturity_date - value_date) start-date fallback. With no origination
        # source the conservative MR 50% default (from sa_ccf_expression) stands.
        if not is_b31:
            exposures = self._apply_oc_original_maturity_ccf(exposures)

        # PRA PS1/26 Art. 111(1) Table A1 Row 4(b): commitments to extend credit
        # secured by residential property attract a 50% CCF — "to the extent
        # that they are not subject to a conversion factor of 10% or 100%". The
        # override lands on BOTH the SA and the F-IRB carrier because Art. 166C(1)
        # defines the F-IRB / Slotting CCF as the Art. 111 SA CCF (P1.251).
        # No effect under CRR (Table A1 is Basel 3.1 only) — see the gate below.
        if is_b31:
            exposures = self._apply_uk_residential_mortgage_ccf(exposures, denomination_ccy)

        # PS1/26 Art. 111(1)(c): commitment-to-issue lower-of rule — "the lower
        # of (i) the CCF applicable to the underlying OBS item and (ii) the CCF
        # applicable to the commitment type".
        #
        # BASEL 3.1 ONLY. CRR Art. 111(1) has no such provision: it lists the
        # four percentages and nothing else — "(a) 100 % if it is a full-risk
        # item; (b) 50 % ... medium-risk; (c) 20 % ... medium/low-risk; (d) 0 %
        # ... low-risk", followed by "The off-balance sheet items ... shall be
        # assigned to risk categories as indicated in Annex I" and the Art. 223
        # volatility-adjustment sentence. Applying the cap under CRR let a
        # commitment to issue a low-risk item drop a full-risk commitment from
        # 100% straight to 0% on the strength of a rule that regime does not
        # contain (P1.265).
        #
        # ⚠ The reference is a genuine trap: PS1/26 Art. 111(1)(c) IS the
        # lower-of rule, while CRR Art. 111(1)(c) is "20 % if it is a
        # medium/low-risk item". Same address, unrelated provisions — do not
        # read a CRR citation of 111(1)(c) as authority for this cap.
        #
        # Gated on the ``firb_uses_sa_ccf`` pack Feature (the same carrier the
        # Table A1 overrides above use) rather than on a config regime flag,
        # per arch_check check 17.
        if is_b31:
            exposures = exposures.with_columns(
                commitment_to_issue_ccf_expression(pl.col("_sa_ccf_from_risk_type")).alias(
                    "_sa_ccf_from_risk_type"
                ),
                commitment_to_issue_ccf_expression(pl.col("_firb_ccf_from_risk_type")).alias(
                    "_firb_ccf_from_risk_type"
                ),
            )

        # PS1/26 Art. 166A(5): the IRB-only, final purchased-receivables
        # commitment CCF. Written to the IRB carrier only — the SA keeps its
        # Table A1 bucket — and applied last so nothing above can move it (TR-02).
        applies_166a5 = resolved_pack.feature("irb_purchased_receivable_commitment_ccf_applies")
        if applies_166a5:
            exposures = self._apply_purchased_receivable_ccf(exposures, resolved_pack)

        # A-IRB CCF: use modelled value, with Basel 3.1 restrictions
        ccf_modelled_expr = pl.col("ccf_modelled").cast(pl.Float64, strict=False)
        if is_b31:
            # Basel 3.1 Art. 166D(1)(a): own-estimate CCFs only "for revolving
            # loan commitments which would not be subject to a 100% conversion
            # factor" under Art. 111; (b) "for all other off-balance sheet items"
            # the SA conversion factor. A "commitment" is, by the PS1/26 glossary,
            # "not itself an issued off-balance sheet item", so an issued LC or
            # guarantee booked under a revolving facility (``is_obs_commitment``
            # False — it inherits the parent's ``is_revolving``) takes limb (b)
            # (CM-03). A null commitment flag cannot evidence limb (a): the AND
            # stays null and the fill sends it to the SA factor (conservative).
            # Eligible rows: own CCF with the 50% SA floor (Art. 166D(5)(a)).
            airb_revolving_ccf = pl.max_horizontal(
                ccf_modelled_expr.fill_null(pl.col("_sa_ccf_from_risk_type")),
                pl.col("_sa_ccf_from_risk_type")
                * scalar_value(resolved_pack.scalar_param("airb_revolving_ccf_floor_multiplier")),
            )
            is_eligible_for_own_ccf = _is_revolving_loan_commitment() & (
                pl.col("_sa_ccf_from_risk_type") < 1.0
            )
            airb_ccf = (
                pl.when(is_eligible_for_own_ccf)
                .then(airb_revolving_ccf)
                .otherwise(pl.col("_sa_ccf_from_risk_type"))
            )
        else:
            # CRR Art. 166(9): own-estimate (modelled) A-IRB CCFs are admissible
            # only within the Art. 166(8) product scope — undrawn commitments
            # (``is_obs_commitment``) and short-term trade LCs
            # (``is_short_term_trade_lc``) — and never for FR/FRC full-risk
            # substitutes. Out-of-scope rows (issued OBS items governed by
            # Art. 166(10), full-risk items) take the supervisory F-IRB CCF
            # unconditionally, so a spuriously low modelled value is ignored.
            # In scope, a null modelled CCF falls back to the Art. 166(8)/(10)
            # supervisory value (``_firb_ccf_from_risk_type``), NOT the SA
            # Art. 111 CCF.
            in_166_8_scope = (
                pl.col("is_obs_commitment").fill_null(True)
                | pl.col("is_short_term_trade_lc").fill_null(False)
            ) & ~_normalize_risk_type("risk_type").is_in(["FR", "FRC"])
            airb_ccf = (
                pl.when(in_166_8_scope)
                .then(ccf_modelled_expr.fill_null(pl.col("_firb_ccf_from_risk_type")))
                .otherwise(pl.col("_firb_ccf_from_risk_type"))
            )

        if applies_166a5:
            # Art. 166A(5) "shall ... 40%" (10% for a Table A1 point 7 UCC) binds
            # the A-IRB too (Art. 166A(1) makes 166A govern every IRB route): no
            # own-estimate limb, so the flagged row takes the IRB carrier outright.
            airb_ccf = (
                pl.when(_is_revolving_purchased_receivable_commitment())
                .then(pl.col("_firb_ccf_from_risk_type"))
                .otherwise(airb_ccf)
            )

        # Select final CCF based on approach
        return exposures.with_columns(
            pl.when(pl.col("_nominal_is_zero"))
            .then(pl.lit(0.0))
            .when(pl.col("approach") == ApproachType.AIRB.value)
            .then(airb_ccf)
            # F-IRB and slotting read the IRB supervisory carrier. CRR Art. 147(8):
            # specialised-lending slotting is a corporate IRB exposure, so its OBS
            # EAD is governed by Art. 166(8) — the F-IRB CCF (e.g. MR -> 75%), not
            # the SA 50%. Under Basel 3.1, Art. 166C(1) makes the F-IRB / slotting
            # carrier the SA Table A1 factor (identical to the SA carrier) except
            # where Art. 166A(5) — an IRB rule — fixes it for a revolving
            # purchased-receivables commitment.
            .when(pl.col("approach").is_in([ApproachType.FIRB.value, ApproachType.SLOTTING.value]))
            .then(pl.col("_firb_ccf_from_risk_type"))
            .otherwise(pl.col("_sa_ccf_from_risk_type"))
            .alias("ccf"),
        )

    # CRR Art. 111(1) / Annex I items 2(b) (MR 50%, original maturity > 1yr) and
    # 3(b) (MLR 20%, original maturity <= 1yr). The MR/MLR split keys on ORIGINAL,
    # not residual, maturity — see the oc_short_maturity_threshold_days scalar.
    @cites("CRR Art. 111(1)")
    def _apply_oc_original_maturity_ccf(
        self,
        exposures: pl.LazyFrame,
    ) -> pl.LazyFrame:
        """Remap the OC ("other commitments") SA CCF on ORIGINAL maturity (CRR).

        CRR Annex I items 2(b)/3(b) split "other commitments" on their ORIGINAL
        maturity: 50% (MR) when > 1yr, 20% (MLR) when <= 1yr. ``sa_ccf_expression``
        supplies the conservative 50% MR default; this override drops the CCF to
        the 20% MLR rate only where an original-maturity source exists and is at
        or below the ``oc_short_maturity_threshold_days`` (365-day) boundary.

        Original maturity is taken from ``original_maturity_years`` when present,
        else the ``(maturity_date - value_date)`` start-date fallback. With neither
        source the row keeps the conservative 50% MR default: the days are null,
        and :func:`oc_original_maturity_ccf_expression` leaves a null untouched.
        """
        schema_names = exposures.collect_schema().names()

        # Preferred explicit source: original_maturity_years (years -> days on a
        # 365-day year, matching the oc_short_maturity_threshold_days scalar).
        if "original_maturity_years" in schema_names:
            original_years_available = pl.col("original_maturity_years").is_not_null()
            original_years_days = (
                pl.col("original_maturity_years").cast(pl.Float64, strict=False) * 365.0
            )
        else:
            original_years_available = pl.lit(False)
            original_years_days = pl.lit(None, dtype=pl.Float64)

        # Fallback source: (maturity_date - value_date) in days, null when either
        # date is null.
        if "maturity_date" in schema_names and "value_date" in schema_names:
            start_days = original_maturity_days_expression()
        else:
            start_days = pl.lit(None, dtype=pl.Float64)

        original_maturity_days = (
            pl.when(original_years_available).then(original_years_days).otherwise(start_days)
        )

        return exposures.with_columns(
            oc_original_maturity_ccf_expression(
                pl.col("_sa_ccf_from_risk_type"), original_maturity_days
            ).alias("_sa_ccf_from_risk_type"),
        )

    # PRA PS1/26 Art. 111(1) Table A1 Row 4(b), read into the F-IRB / Slotting
    # exposure value by Art. 166C(1). Art. 166C has no CRR equivalent and the
    # watchfire PS-instrument grammar only accepts numeric paragraphs, so Art.
    # 166C para 1 is encoded as section 166.1 (see the Art. 166A(5) note below
    # and docs/development/citation-tracking.md on the PS1/26 form).
    @cites("PS1/26, paragraph 111")
    @cites("PS1/26, paragraph 166.1")
    def _apply_uk_residential_mortgage_ccf(
        self,
        exposures: pl.LazyFrame,
        denomination_ccy: pl.Expr,
    ) -> pl.LazyFrame:
        """Apply the Table A1 Row 4(b) UK residential-mortgage commitment CCF.

        PRA PS1/26 Art. 111(1) Table A1 Row 4(b): "UK residential mortgage
        commitments that are not subject to a conversion factor of 10% or 100%"
        attract a 50% conversion factor (Row 5, "any other commitment", is 40%).
        A row is a Row 4(b) commitment when ``is_uk_residential_mortgage_
        commitment`` is True, or — when the flag is null (not stated) — when
        :func:`_derived_uk_residential_mortgage_commitment` evidences it (RE-14:
        the flag was never derived, so an ordinary UK mortgage offer took 40%).
        An explicit False is honoured. The otherwise-resolved CCF is overridden to
        the Row 4 rate (50%) unless the row already sits in the carve-out — the
        Row 7 UCC 10% or the Row 1/2 100% — in which case it is left untouched.
        The carve-out is tested per carrier, against that carrier's own value.

        Both the SA and the IRB carrier are patched: Art. 166C(1) sets the F-IRB
        and Slotting off-balance-sheet exposure value using "the conversion factor
        that would be applicable to the off-balance sheet item under the
        Standardised Approach, as set out in ... Article 111", so Row 4(b) governs
        the F-IRB conversion factor exactly as it governs the SA one (P1.251).

        Basel-3.1-only: callers gate this on the ``firb_uses_sa_ccf`` pack Feature
        (S9c); Table A1 Row 4(b) is a PRA construct with no CRR Annex I
        equivalent, so the flag is a no-op under CRR.
        """
        # A null that the evidence cannot settle stays null, and ``when(null)``
        # takes the ``otherwise`` branch: the row keeps its bucket.
        is_resi_commitment = pl.col("is_uk_residential_mortgage_commitment").fill_null(
            _derived_uk_residential_mortgage_commitment(denomination_ccy)
        )
        return exposures.with_columns(
            uk_residential_mortgage_ccf_expression(
                pl.col("_sa_ccf_from_risk_type"), is_resi_commitment
            ).alias("_sa_ccf_from_risk_type"),
            uk_residential_mortgage_ccf_expression(
                pl.col("_firb_ccf_from_risk_type"), is_resi_commitment
            ).alias("_firb_ccf_from_risk_type"),
        )

    # PRA PS1/26 Art. 166A(5) — no CRR equivalent; the watchfire PS-instrument
    # grammar only accepts numeric paragraphs, so Art. 166A para 5 is encoded as
    # section 166.5 (see docs/development/citation-tracking.md on the PS1/26 form).
    @cites("PS1/26, paragraph 166.5")
    def _apply_purchased_receivable_ccf(
        self,
        exposures: pl.LazyFrame,
        pack: ResolvedRulepack,
    ) -> pl.LazyFrame:
        """Apply the Art. 166A(5) revolving purchased-receivables IRB CCF.

        PRA PS1/26 Art. 166A(5), second subparagraph: "An institution shall, for
        undrawn purchase commitments for revolving purchased receivables,
        calculate the exposure value using a conversion factor of 40%, except
        where such commitments meet the criteria set out in point 7 of Column A of
        Table A1 ... in which case the conversion factor shall be 10%." Point 7 is
        the unconditionally cancellable commitment, i.e. the ``LR`` bucket. When
        ``is_purchased_receivable_commitment`` and ``is_revolving`` are both True
        the IRB carrier is overridden to that factor whatever the row's bucket.

        The rule sits in the IRB Part and governs every IRB route (Art. 166A(1):
        F-IRB and slotting via 166C, A-IRB via 166D), so ONLY the IRB carrier
        (``_firb_ccf_from_risk_type``) is patched; ``_compute_ccf`` hands it to
        flagged A-IRB rows outright (no own-estimate limb). The Standardised
        Approach has no such rule: an SA row keeps its Table A1 bucket — a
        factoring line with recourse is Row 2(a) 100%, not 40% (TR-02).

        Gated by the caller on the ``irb_purchased_receivable_commitment_ccf_
        applies`` pack Feature (Basel 3.1 only; CRR Art. 166(8)(c) prices the
        cancellable case through the LR bucket and has no fixed 40%).
        """
        commitment_ccf = scalar_value(pack.scalar_param("irb_purchased_receivable_commitment_ccf"))
        ucc_ccf = scalar_value(pack.scalar_param("irb_purchased_receivable_commitment_ucc_ccf"))
        is_ucc = _normalize_risk_type("risk_type") == "LR"
        pr_ccf = pl.when(is_ucc).then(pl.lit(ucc_ccf)).otherwise(pl.lit(commitment_ccf))

        return exposures.with_columns(
            pl.when(_is_revolving_purchased_receivable_commitment())
            .then(pr_ccf)
            .otherwise(pl.col("_firb_ccf_from_risk_type"))
            .alias("_firb_ccf_from_risk_type"),
        )

    def _compute_ead(
        self,
        exposures: pl.LazyFrame,
        has_provision_cols: bool,
        config: CalculationConfig,
        *,
        pack: ResolvedRulepack | None = None,
    ) -> pl.LazyFrame:
        """Calculate EAD from CCF-adjusted undrawn and on-balance-sheet components.

        Provision deduction (CRR Art. 111(2)) is applied only when both
        provision columns were present in the original input.

        For A-IRB under Basel 3.1, applies Art. 166D(5) EAD floors:
        (b) When ead_modelled is provided on a revolving loan commitment (Art.
            166D(3) single-EAD approach; any other row ignores it and keeps its
            Art. 166D(1)(b) / 166A(5) exposure value):
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

        # Art. 166D(5) EAD floors — Basel 3.1 A-IRB only (S9c: gated on the cited
        # pack Feature; the 0.5 floor multiplier stays a static data-layer constant).
        resolved_pack = pack if pack is not None else RulepackV0.from_config(config).pack
        if resolved_pack.feature("airb_ead_floor_applies"):
            is_airb = pl.col("approach") == ApproachType.AIRB.value
            # Art. 166D(3)/(4): a single own estimate of EAD only for a revolving
            # loan FACILITY — "instead of the exposure values that would otherwise
            # be assigned to the revolving loan commitment". An issued item, a
            # non-revolving commitment or a flagged revolving purchased-receivables
            # commitment (Art. 166A(5) "shall ... 40%") keeps its paragraph 1 /
            # 166A(5) exposure value whatever ``ead_modelled`` it carries.
            own_ead_population = _is_revolving_loan_commitment()
            if resolved_pack.feature("irb_purchased_receivable_commitment_ccf_applies"):
                own_ead_population = (
                    own_ead_population & ~_is_revolving_purchased_receivable_commitment()
                )
            has_modelled_ead = pl.col("ead_modelled").is_not_null() & own_ead_population

            # Floor (b): facility-level EAD floor for Art. 166D(3) single-EAD approach
            # EAD >= on-BS EAD + 50% x (nominal x SA_CCF)
            # Under B31, F-IRB CCFs = SA CCFs (Art. 166C)
            floor_b = pl.col("on_bs_for_ead") + pl.col("nominal_after_provision") * pl.col(
                "_sa_ccf_from_risk_type"
            ) * scalar_value(resolved_pack.scalar_param("airb_obs_floor_b_multiplier"))

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


@cites("PS1/26, paragraph 166D")
def _is_revolving_loan_commitment() -> pl.Expr:
    """True for a revolving loan COMMITMENT — the PS1/26 Art. 166D own-estimate population.

    Art. 166D(1)(a) (own conversion factor) and 166D(3)/(4) (single own estimate
    of EAD) both reach only a revolving loan commitment: ``is_revolving`` AND
    ``is_obs_commitment`` — a commitment is "not itself an issued off-balance
    sheet item" (PS1/26 glossary), so an issued LC or guarantee booked under a
    revolving facility is outside it (CM-03). A null in either cannot evidence
    the rule, so the AND is filled False and the row takes the SA factor
    (Art. 166D(1)(b)). Shared by the two routes so they can never test different
    populations.
    """
    return (pl.col("is_revolving") & pl.col("is_obs_commitment")).fill_null(False)


def _is_revolving_purchased_receivable_commitment() -> pl.Expr:
    """True for an undrawn purchase commitment of a REVOLVING purchased-receivables facility.

    The PS1/26 Art. 166A(5) population: ``is_purchased_receivable_commitment``
    AND ``is_revolving``. A null in either cannot evidence the rule, so the AND
    is filled False and the row keeps its ordinary conversion factor. Shared by
    the IRB-carrier override and the A-IRB selection so the two can never test
    different populations.
    """
    return (pl.col("is_purchased_receivable_commitment") & pl.col("is_revolving")).fill_null(False)


def _derived_uk_residential_mortgage_commitment(denomination_ccy: pl.Expr) -> pl.Expr:
    """Evidence that an unflagged row is a PS1/26 Table A1 Row 4(b) commitment (RE-14).

    True only when every limb is evidenced on the row:

    - a COMMITMENT (``is_obs_commitment``) — an issued item is never Row 4(b);
    - a RETAIL MORTGAGE (``exposure_class == retail_mortgage``) actually secured on
      residential property: the classifier also routes commercial-property-secured
      retail rows to ``retail_mortgage``, so the residential evidence is what makes
      it a *residential* mortgage. Two carriers, either suffices: an allocated
      ``residential_collateral_value > 0``, or the linked property's
      ``property_type == "residential"``. The second is needed because facility-
      level collateral is allocated pro rata to DRAWN amounts, so a facility's
      undrawn row carries ``residential_collateral_value`` 0 even when the whole
      facility is secured on a house;
    - UK. The data model carries no property location (P1.337), so "UK" is
      evidenced by a GB obligor AND a GBP denomination — the engine's existing
      UK-domestic test (``engine/sa/risk_weights.py``), read on the pre-FX
      ``denomination_ccy``. A row failing either keeps its Row 5 40%: this never
      moves a commitment it cannot show to be UK. A UK mortgage to a non-GB
      obligor needs the flag set True; a GB obligor's non-UK property, False.

    A null anywhere yields null or False, so an unevidenced row is left alone.
    """
    secured_on_residential_property = (pl.col("residential_collateral_value") > 0.0) | (
        pl.col("property_type").str.to_lowercase() == "residential"
    )
    return (
        pl.col("is_obs_commitment")
        & (pl.col("exposure_class") == ExposureClass.RETAIL_MORTGAGE.value)
        & secured_on_residential_property
        & (pl.col("cp_country_code") == "GB")
        & (denomination_ccy == "GBP")
    )
