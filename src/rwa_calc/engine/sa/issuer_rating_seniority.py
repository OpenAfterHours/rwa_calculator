"""
CRR Art. 139(2) seniority test for credit assessments that are not the item's own.

Pipeline position:
    CRMProcessor -> SACalculator (engine/sa/risk_weights.py) -> OutputAggregator
    ``apply_issuer_rating_seniority_test`` runs in ``_prepare_risk_weight_lookup``
    after the pre-ladder CQS lifts and the PS1/26 Art. 139(2B) SL nulling, and
    before the CQS risk-weight table join. ``crr_unrated_corporate_rw_expr``,
    ``crr_unrated_institution_rw_expr`` and ``crr_sme_managed_as_retail_expr``
    are ALSO the CRR override ladder's own unrated-corporate, unrated-institution
    and SME-as-retail branches.

Key responsibilities:
- ``apply_issuer_rating_seniority_test``: treat a subordinated institution,
  corporate or specialised-lending exposure as unrated (null ``cqs``) where the
  credit assessment it carries is not its own and gives a LOWER risk weight than
  the unrated treatment.
- ``crr_unrated_corporate_rw_expr``: the CRR Art. 122(2) unrated corporate weight.
- ``crr_unrated_institution_rw_expr``: the CRR Art. 121(1)-(3) unrated institution
  weight.
- ``crr_sme_managed_as_retail_expr``: which SME rows the CRR ladder weights as
  retail (Art. 123), whatever their rating.

The rule. CRR Art. 139(2): where no directly applicable assessment exists for an
item but one exists for the issuer (or for another of its issues), "that credit
assessment shall be used in either of the following cases: (a) it produces a
higher risk weight than would otherwise be the case and the exposure in question
ranks pari passu or junior ...; (b) it produces a lower risk weight and the
exposure in question ranks pari passu or senior .... In all other cases, the
exposure shall be treated as unrated." A subordinated exposure ranks junior, so
limb (b) never reaches it: it keeps the assessment only where that gives the
higher weight, and its weight is ``max(rated, unrated)``. PS1/26 Art. 139(2)
keeps both limbs with the same operative words (the provision survives).

Which assessments are Art. 139(2) assessments. The hierarchy attaches every
long-term rating counterparty-wide (``engine/hierarchy/ratings.py``) and cannot
attach one to an item, so for a subordinated item a long-term rating is never
"directly applicable", whatever the defaulted ``external_rating_is_issue_specific``
flag says; that flag keeps its one job, the PS1/26 Art. 139(2B) SL nulling. The
item's own assessment is an exposure-scoped short-term issue rating
(``has_own_short_term_ecai``) — Art. 139(1) — and is never touched. A short-term
rating spilled onto the leg from another facility (Art. 120(3)(c)) is not the
leg's own and is tested like any other.

Why the test can only raise a weight. Nulling ``cqs`` hands the row to the
ladder's unrated branches and makes it an Art. 140(2) target, so the row then
carries the ladder's unrated weight raised by Art. 140(2); the test fires only
where the rated weight is strictly below THAT weight. That holds only while the
comparison's unrated weight is the one the engine then assigns — which is why
the unrated builders live here and the ladder calls them, and why the Art. 140(2)
half is read from ``engine/sa/obligor_st_contamination.py``, the override's own
expression. Two wrong comparison bases have been measured:

- the rating TABLE's unrated institution row (100%): an unrated institution
  takes its sovereign's Art. 121(1) weight, so a CQS 2 (50%) institution in a
  CQS 1 sovereign (20%) would be cut to 20%;
- the ladder's unrated weight WITHOUT Art. 140(2): where the obligor carries a
  150% short-term facility every unrated unsecured exposure to it takes 150%
  (Art. 140(2)(a)), so a subordinated CQS 3 corporate (100%) kept its rating at
  100% while a CQS 2 one moved to 150% — non-monotone in credit quality and
  below Art. 139(2) for both. Likewise Art. 140(2)(b)'s 100% floor on unrated
  short-term exposures where the obligor carries a 50% short-term facility.

The rated side mirrors the ladder's precedence: an SME managed as retail takes
the Art. 123 retail weight with or without its rating (so only Art. 140(2) can
separate its two weights), then Table 7 / Table 4 / Table 3 / corporate table.
One ladder branch is not modelled: an in-scope row with ``property_type ==
"commercial"`` goes to ``crr_commercial_re_rw_expr`` (``re_class.py``) ahead of
every corporate branch, so the comparison judges only its corporate weight. That
is still right: Art. 139(2) acts on the Art. 126 residual, which the nulled
``cqs`` then weights as unrated (a subordinated CQS 2 corporate meeting Art. 126
at LTV 0.8 moves from 50% to 68.75%).
The Art. 140(2) half is applied to the unrated side only: a rated row is a
target only through an Art. 120(3)(c) spilled short-term rating, and there both
sides end on the same contaminated weight, so leaving it out changes whether
``cqs`` is nulled but never the weight.

Rows the ladder weights without any Chapter 2 credit assessment are outside the
test: the own-funds lines (settlement risk and CCP default fund, Art. 92(3)(ca)
-> 1250%) and QCCP trade exposures (CCR Part Art. 306). Nulling ``cqs`` on an
own-funds line would make it an Art. 140(2) target and overwrite its 1250%
with 150% — a capital cut.

Why the CRR ladder only. On the PS1/26 ladder Art. 133(5) assigns 150% to a
subordinated institution, corporate or specialised-lending exposure whatever its
rating (``engine/sa/subordinated_debt.py``), so its rated and unrated weights are
both 150% and the test cannot move it. The test therefore reads the cited
ladder-dispatch Feature ``sa_revised_risk_weight_overrides``; it does not assert
that Art. 139(2) is CRR-only.

Equal weights are not a gap: Art. 139(2) treats such a row as unrated, and
because the comparison's unrated weight already carries Art. 140(2), the
unrated weight IS the rated one; ``cqs`` is kept, and the row's weight is
``max(rated, unrated)`` either way.

Residuals, not handled here:
- Subordinated central-government, PSE, RGLA and MDB rows (both regimes; the
  quasi-sovereigns sit outside the Art. 133(5) predicate pending review IV-03).
- Real-estate classes (``residential_mortgage``, ``commercial_mortgage``) read
  the counterparty's corporate ``cqs`` for the part above the LTV threshold
  (``crr_real_estate.py``, ``re_residual_rw.py``) and are outside this test's
  class scope; a subordinated rated one keeps its rated corporate weight on
  that part.
- Covered bonds are out of scope by Art. 139(3).

References:
- CRR Art. 139(1)/(2); PRA PS1/26 Art. 139(1)/(2); PRA PS1/26 Art. 133(5)
- CRR Art. 122(1)/(2): corporate rated / unrated weights
- CRR Art. 120(1) Table 3, 120(2) Table 4, 121(1)-(4): institution weights
- CRR Art. 131 Table 7: short-term credit assessments
- CRR Art. 140(2); PRA PS1/26 Art. 140(2): obligor short-term contamination
- CRR Art. 123: SME exposures weighted as retail
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.domain.enums import CQS
from rwa_calc.engine.crm.own_funds_lines import own_funds_line_expr
from rwa_calc.engine.sa.ccp_exposures import qccp_trade_exposure_expr
from rwa_calc.engine.sa.crr_risk_weight_tables import (
    CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
    CORPORATE_RISK_WEIGHTS,
    CRR_CORPORATE_SME_RW,
    CRR_SHORT_TERM_ECAI_RISK_WEIGHTS,
    INSTITUTION_RISK_WEIGHTS_CRR,
    INSTITUTION_RISK_WEIGHTS_SOVEREIGN_DERIVED,
    INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR,
    INSTITUTION_SHORT_TERM_UNRATED_RW_CRR,
)
from rwa_calc.engine.sa.obligor_st_contamination import art_140_2_target_rw_expr
from rwa_calc.engine.sa.sovereign_derived import (
    cqs_table_lookup_expr,
    crr_art_121_4_trade_finance_expr,
    sovereign_derived_rw_expr,
)
from rwa_calc.engine.sa.subordinated_debt import is_subordinated
from rwa_calc.rulebook.compile import scalar_value

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)


@cites("CRR Art. 139")
@cites("PS1/26, paragraph 139")
def apply_issuer_rating_seniority_test(
    exposures: pl.LazyFrame,
    upper_class: pl.Expr,
    pack: ResolvedRulepack,
    reporting_date: date,
) -> pl.LazyFrame:
    """Treat a junior row as unrated where its borrowed rating gives the lower weight.

    Args:
        exposures: SA frame after ``ensure_columns`` and the pre-ladder lifts,
            before the CQS table join (so the join sees the nulled ``cqs``).
        upper_class: ``exposure_class`` upper-cased by the caller.
        pack: the run's resolved rulepack.
        reporting_date: dates the residual maturity that scopes Art. 121(4)
            trade finance in the unrated institution weight.

    Returns:
        ``exposures`` with ``cqs`` nulled on the rows Art. 139(2) treats as
        unrated; every other row and column is unchanged.
    """
    if pack.feature("sa_revised_risk_weight_overrides"):
        # PS1/26 Art. 133(5) pins every in-scope row at 150%; see module docstring.
        return exposures
    in_scope = (
        upper_class.str.contains("INSTITUTION", literal=True)
        | upper_class.str.contains("CORPORATE", literal=True)
        | upper_class.str.contains("SPECIALISED", literal=True)
    ) & ~(own_funds_line_expr() | qccp_trade_exposure_expr())
    borrowed_rating = pl.col("has_own_short_term_ecai").not_() & (pl.col("cqs") > 0)
    retail_rw = scalar_value(pack.scalar_param("retail_risk_weight"))
    unrated_institution = crr_unrated_institution_rw_expr(
        reporting_date,
        scalar_value(
            pack.scalar_param("sa_unrated_institution_trade_finance_max_residual_maturity_years")
        ),
    )
    rated_lower = _crr_rated_rw_expr(upper_class, retail_rw) < _crr_unrated_rw_expr(
        upper_class, retail_rw, unrated_institution
    )
    return exposures.with_columns(
        pl.when(is_subordinated() & in_scope & borrowed_rating & rated_lower)
        .then(pl.lit(None, dtype=pl.Int8))
        .otherwise(pl.col("cqs"))
        .alias("cqs")
    )


@cites("CRR Art. 122")
def crr_unrated_corporate_rw_expr() -> pl.Expr:
    """CRR Art. 122(2) weight of an unrated corporate.

    Art. 122(2): "a 100 % risk weight or the risk weight of exposures to the
    central government of the jurisdiction in which the corporate is
    incorporated, whichever is the HIGHER". Only a CQS 6 sovereign (150%) binds:
    the Art. 114 ladder is 0/20/50/100/100/150 and an unrated sovereign is 100%.

    Covers SME and non-SME alike: Art. 122 draws no SME distinction, and CRR SME
    relief is the Art. 501 supporting factor, not a risk weight. Read by the CRR
    override ladder's unrated-corporate branch and by the Art. 139(2) test.
    """
    return pl.max_horizontal(
        pl.lit(float(CRR_CORPORATE_SME_RW)),
        sovereign_derived_rw_expr(
            CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS,
            float(CENTRAL_GOVT_CENTRAL_BANK_RISK_WEIGHTS[CQS.UNRATED]),
        ),
    )


@cites("CRR Art. 121")
def crr_unrated_institution_rw_expr(
    reporting_date: date, trade_finance_max_residual_years: float
) -> pl.Expr:
    """CRR Art. 121 weight of an unrated institution, short-dated first.

    - Art. 121(3): original effective maturity of three months or less -> 20%.
      Takes precedence over the Table 5 lookup; the Art. 121(6) sovereign floor
      (Basel 3.1 only, applied later) can still raise it.
    - Art. 121(1) Table 5: the risk weight of the CQS to which the central
      government of the institution's jurisdiction of incorporation is
      assigned — 1/2/3/4/5/6 -> 20/50/100/100/100/150%. Art. 121(2) (central
      government unrated -> 100%) is the ``unrated_default`` that
      ``sovereign_derived_rw_expr`` applies when ``cp_sovereign_cqs`` is null.
    - Art. 121(4) trade finance (Art. 162(3)(b), RESIDUAL maturity up to
      ``trade_finance_max_residual_years`` from ``reporting_date``, P1.316) is
      held OUT of Table 5 (see ``crr_art_121_4_trade_finance_expr``) and takes
      the Art. 121 unrated 100% residual; a trade LC with longer to run takes
      Table 5. That is a deliberate interim, conservative against both
      candidate readings of Art. 121(4) (50% purposive, 20% literal at sovereign
      CQS 1), pinned by ``test_p1_316_trade_finance_stays_on_the_100pct_residual``
      so the value cannot drift between the three candidates; P1.326 / P7.8 own
      the rate.

    Read by the CRR override ladder's unrated-institution branch and by the
    Art. 139(2) test.
    """
    unrated_residual = float(INSTITUTION_RISK_WEIGHTS_CRR[CQS.UNRATED])
    return (
        pl.when(pl.col("original_maturity_years") <= 0.25)
        .then(pl.lit(float(INSTITUTION_SHORT_TERM_UNRATED_RW_CRR)))
        .when(~crr_art_121_4_trade_finance_expr(reporting_date, trade_finance_max_residual_years))
        .then(
            sovereign_derived_rw_expr(INSTITUTION_RISK_WEIGHTS_SOVEREIGN_DERIVED, unrated_residual)
        )
        .otherwise(pl.lit(unrated_residual))
    )


@cites("CRR Art. 123")
def crr_sme_managed_as_retail_expr(upper_class: pl.Expr) -> pl.Expr:
    """True on an SME row the CRR ladder weights as retail (Art. 123, 75%).

    The SME is managed as retail and qualifies as retail (aggregated exposure
    within the Art. 123 limit). The ladder's branch ignores ``cqs``, so the
    row's rated and unrated ladder weights are the same. Read by the CRR
    override ladder's SME-as-retail branch and by the Art. 139(2) test.
    """
    return (
        upper_class.str.contains("SME", literal=True)
        & (pl.col("cp_is_managed_as_retail") == True)  # noqa: E712
        & (pl.col("qualifies_as_retail") == True)  # noqa: E712
    )


def _crr_rated_rw_expr(upper_class: pl.Expr, retail_rw: float) -> pl.Expr:
    """Weight the CRR ladder gives a rated institution / corporate / SL row on its ``cqs``.

    Mirrors the ladder's precedence: the Art. 123 retail weight for an SME
    managed as retail (its rating is not read), Art. 131 Table 7 where the row
    carries a short-term assessment (institutions; non-SME corporates),
    Art. 120(2) Table 4 for a short-dated institution, else Art. 120(1) Table 3
    or the Art. 122(1) corporate table. Null outside CQS 1-6, so the test never
    fires on a rating the tables do not define.
    """
    is_institution = upper_class.str.contains("INSTITUTION", literal=True)
    is_corporate = upper_class.str.contains("CORPORATE", literal=True)
    has_st_ecai = pl.col("has_short_term_ecai")
    short_dated = (pl.col("residual_maturity_years") <= 0.25) | (
        pl.col("original_maturity_years") <= 0.25
    )
    table_7 = _rated_lookup(CRR_SHORT_TERM_ECAI_RISK_WEIGHTS)
    return (
        pl.when(crr_sme_managed_as_retail_expr(upper_class))
        .then(pl.lit(retail_rw))
        .when(is_institution & has_st_ecai)
        .then(table_7)
        .when(is_institution & short_dated)
        .then(_rated_lookup(INSTITUTION_SHORT_TERM_RISK_WEIGHTS_CRR))
        .when(is_institution)
        .then(_rated_lookup(INSTITUTION_RISK_WEIGHTS_CRR))
        .when(is_corporate & ~upper_class.str.contains("SME", literal=True) & has_st_ecai)
        .then(table_7)
        .otherwise(_rated_lookup(CORPORATE_RISK_WEIGHTS))
    )


def _crr_unrated_rw_expr(
    upper_class: pl.Expr, retail_rw: float, unrated_institution: pl.Expr
) -> pl.Expr:
    """Weight the same row takes once it is treated as unrated: ladder, then Art. 140(2).

    The ladder half: an SME managed as retail keeps the Art. 123 retail weight;
    a specialised-lending row matches no unrated branch and lands on the
    corporate table's unrated row through the base CQS join.

    The Art. 140(2) half is part of "the risk weight ... than would otherwise
    be the case": a row treated as unrated, with no short-term assessment of
    its own, is an Art. 140(2) target, so where its obligor carries a 150%
    short-term facility it takes 150%, and where the obligor carries a 50% one
    a short-term leg takes at least 100%. Leaving that half out compares
    against too low a weight: a subordinated CQS 3 corporate (100%) of a
    contaminated obligor kept its rating at 100% while a CQS 2 one went to
    150% — non-monotone in credit quality, and below Art. 139(2) for both.
    """
    ladder_unrated = (
        pl.when(crr_sme_managed_as_retail_expr(upper_class))
        .then(pl.lit(retail_rw))
        .when(upper_class.str.contains("INSTITUTION", literal=True))
        .then(unrated_institution)
        .when(upper_class.str.contains("CORPORATE", literal=True))
        .then(crr_unrated_corporate_rw_expr())
        .otherwise(pl.lit(float(CORPORATE_RISK_WEIGHTS[CQS.UNRATED])))
    )
    return art_140_2_target_rw_expr(ladder_unrated)


def _rated_lookup(table: dict[CQS, Decimal]) -> pl.Expr:
    """Map ``cqs`` 1-6 onto ``table``; null for any other value."""
    return cqs_table_lookup_expr("cqs", table, pl.lit(None, dtype=pl.Float64))
