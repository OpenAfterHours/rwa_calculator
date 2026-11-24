"""
Dual rating-inheritance resolution for the hierarchy stage.

Pipeline position:
    Loader -> HierarchyResolver (engine/hierarchy) -> Classifier
    Sub-module of the hierarchy stage package; consumed by ``graph`` when
    building the sealed CounterpartyLookup.

Key responsibilities:
- Resolve the best internal rating (PD) and best external rating (CQS)
  separately per counterparty (dual per-type resolution).
- Combine multiple external assessments per CRR Art. 138 (second-best rule).
- Inherit internal ratings from the ultimate parent when the entity has no
  own internal rating; external ratings are never inherited.
- Basel 3.1 only (pack Feature ``sa_implicit_support_ratings_disapplied``):
  remove the external (ECAI) assessments PS1/26 Art. 138(1)(g) bars — those
  incorporating implicit government support, on an institution obligor that
  is not government-owned or sponsored — from the ratings table before ANY
  selection reads it (``disregard_implicit_support_ratings``, applied by the
  resolver). Internal ratings are never removed.

References:
- CRR Art. 135: Use of external credit assessments (ECAIs)
- CRR Art. 136: Mapping of ECAI ratings to credit quality steps
- CRR Art. 138: Issuer / issue credit assessment
- PS1/26 Art. 138(1)(g): implicit government support (no CRR equivalent)
- PS1/26 Art. 107(2): exposures to a QCCP / non-QCCP treated as to an
  institution / a corporate; CRR Art. 119(5): financial institutions
- CRR Art. 171(1) / Art. 175(3): internal rating assignment within groups
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.domain.enums import ExposureClass
from rwa_calc.engine.entity_class_maps import entity_types_by_sa_class

if TYPE_CHECKING:
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)


def build_rating_inheritance_lazy(
    counterparties: pl.LazyFrame,
    ratings: pl.LazyFrame,
    ultimate_parents: pl.LazyFrame,
) -> pl.LazyFrame:
    """
    Build rating lookup with dual per-type resolution and inheritance.

    Resolves the best internal and best external rating separately per
    counterparty, then inherits internal ratings from the ultimate parent
    when the entity has no own internal rating. External ratings are NOT
    inherited — they apply only to the counterparty explicitly rated by
    the agency, and when more than one ECAI has rated the counterparty
    they are combined per CRR Art. 138:

      - 1 assessment  -> use it
      - 2 assessments -> use the higher risk weight (worse CQS)
      - >= 3          -> use the higher of the two lowest risk weights
                         (i.e. the second-best rating)

    Repeated assessments from the same agency are first reduced to the
    most recent (one assessment per agency) before Art. 138 is applied.
    Resolution is performed on CQS rather than RW because within every
    SA exposure class the CQS -> RW mapping is monotone non-decreasing,
    so ranking by CQS ascending yields the same outcome as ranking by RW.

    Returns LazyFrame with columns:
    - counterparty_reference: The entity
    - internal_pd: Best internal PD (own or inherited from parent)
    - internal_model_id: Model ID for the internal rating
    - external_cqs: Art. 138-resolved external CQS (own only — not inherited)
    - cqs: Alias of external_cqs
    - pd: Alias of internal_pd

    REVIEWER NOTE: the dual coalesce on internal_pd / internal_model_id
    below (paired ``own → parent`` joins followed by independent
    ``pl.coalesce`` per column) is deliberate per CRR Art. 171(1) and
    Art. 175(3). The asymmetry between internal-inherits and
    external-does-not-inherit is encoded by the *presence* of the
    parent-internal join versus the *absence* of a parent-external one.
    See ``tests/unit/test_hierarchy.py::TestInheritanceTruthTable``
    rows 4, 6, 7 for the behavioural lock — simplification proposals
    (e.g. fusing into a single struct-coalesce, or collapsing the two
    joins into one) must update those rows; do not delete them.
    """
    sort_cols = ["rating_date", "rating_reference"]

    # Counterparty-wide rating aggregates exclude short-term rating rows.
    # Short-term ECAI assessments are issue-specific (PRA PS1/26 Art. 120(2B)
    # / Art. 122(3)) — they attach to a particular exposure and must not
    # leak into the counterparty's long-term aggregate. The per-exposure
    # short-term override is applied separately by
    # ``enrich.apply_short_term_rating_override``. ``is_short_term`` is loader-
    # defaulted to False (Boolean schema default), so no null fill is needed.
    long_term_only = ratings.filter(~pl.col("is_short_term"))

    # Best internal rating per counterparty (no CQS — that's external only)
    best_internal = (
        long_term_only.filter(pl.col("rating_type") == "internal")
        .sort(sort_cols, descending=[True, True])
        .group_by("counterparty_reference")
        .first()
        .select(
            [
                pl.col("counterparty_reference").alias("_int_cp"),
                pl.col("pd").alias("internal_pd"),
                pl.col("model_id").alias("internal_model_id"),
            ]
        )
    )

    # Art. 138: per-agency dedup to most recent, then resolve across agencies.
    # Rows without a CQS are ignored (only rated assessments count).
    # The counterparty_reference.is_not_null filter is defence-in-depth
    # against a downstream .over("counterparty_reference") collapsing all
    # null-keyed ratings into one bucket — the loader contract should
    # already guarantee non-null counterparty_reference on ratings.
    per_agency_latest = (
        long_term_only.filter(
            (pl.col("rating_type") == "external")
            & pl.col("cqs").is_not_null()
            & pl.col("counterparty_reference").is_not_null()
        )
        .sort(sort_cols, descending=[True, True])
        .group_by(["counterparty_reference", "rating_agency"])
        .first()
        .select(["counterparty_reference", "cqs", "rating_is_issue_specific"])
    )

    # Rank CQS ascending per counterparty (lowest CQS == best rating == lowest RW).
    # For 1 assessment: pick rank 1. For >= 2: pick rank 2 -- this yields the
    # higher-RW side of the two lowest RWs, i.e. "worse of two" / "second-best".
    ranked_external = per_agency_latest.with_columns(
        [
            pl.col("cqs").rank(method="ordinal").over("counterparty_reference").alias("_rank"),
            pl.len().over("counterparty_reference").alias("_n"),
        ]
    )

    best_external = ranked_external.filter(
        ((pl.col("_n") == 1) & (pl.col("_rank") == 1))
        | ((pl.col("_n") >= 2) & (pl.col("_rank") == 2))
    ).select(
        [
            pl.col("counterparty_reference").alias("_ext_cp"),
            pl.col("cqs").alias("external_cqs"),
            pl.col("rating_is_issue_specific").alias("external_rating_is_issue_specific"),
        ]
    )

    # Materialise the per-counterparty best-rating aggregates before joining.
    # Each is referenced twice (own rating + parent rating); without this,
    # Polars re-evaluates the filter→sort→group_by chain per reference.
    best_int_df, best_ext_df = pl.collect_all([best_internal, best_external])
    best_internal = best_int_df.lazy()
    best_external = best_ext_df.lazy()

    # Start with all counterparties, join own ratings per type
    result = counterparties.select("counterparty_reference")
    result = result.join(
        best_internal, left_on="counterparty_reference", right_on="_int_cp", how="left"
    )
    result = result.join(
        best_external, left_on="counterparty_reference", right_on="_ext_cp", how="left"
    )

    # Join with ultimate parents for inheritance
    result = result.join(
        ultimate_parents.select(
            [
                pl.col("counterparty_reference").alias("_cp"),
                pl.col("ultimate_parent_reference"),
            ]
        ),
        left_on="counterparty_reference",
        right_on="_cp",
        how="left",
    )

    # Parent's best internal
    parent_internal = best_internal.select(
        [
            pl.col("_int_cp").alias("_p_int_cp"),
            pl.col("internal_pd").alias("parent_internal_pd"),
            pl.col("internal_model_id").alias("parent_internal_model_id"),
        ]
    )
    result = result.join(
        parent_internal,
        left_on="ultimate_parent_reference",
        right_on="_p_int_cp",
        how="left",
    )

    # Internal-only inheritance: coalesce own → parent for internal ratings
    # External ratings are NOT inherited — they stay as the entity's own value
    result = result.with_columns(
        [
            pl.coalesce(pl.col("internal_pd"), pl.col("parent_internal_pd")).alias("internal_pd"),
            pl.coalesce(pl.col("internal_model_id"), pl.col("parent_internal_model_id")).alias(
                "internal_model_id"
            ),
        ]
    )

    # Derive convenience aliases
    result = result.with_columns(
        [
            pl.col("external_cqs").alias("cqs"),
            pl.col("internal_pd").alias("pd"),
        ]
    )

    return result.select(
        [
            "counterparty_reference",
            "internal_pd",
            "internal_model_id",
            "external_cqs",
            "external_rating_is_issue_specific",
            "cqs",
            "pd",
        ]
    )


@cites("PS1/26, paragraph 138")
def disregard_implicit_support_ratings(
    ratings: pl.LazyFrame | None,
    counterparties: pl.LazyFrame,
    pack: ResolvedRulepack,
) -> pl.LazyFrame | None:
    """
    Drop the assessments PS1/26 Art. 138(1)(g) bars, before any selection reads them.

    Art. 138(1)(g): "an institution shall not use a credit assessment that
    incorporates assumptions of implicit government support for the purposes of
    assigning a risk weight to an exposure to an institution, unless the
    respective credit assessment applies to an institution owned by or set up
    and sponsored by central governments, regional governments or local
    authorities." UK CRR Art. 138(1) has limbs (a)-(f) only, so the filter runs
    only where the pack enables ``sa_implicit_support_ratings_disapplied``
    (Basel 3.1); otherwise ``ratings`` is returned unchanged.

    A row is removed when all of the following hold:

    - It is an external (ECAI) assessment: ``rating_type == "external"``,
      matched as the Art. 138 selection matches it. Art. 138 governs credit
      assessments by nominated ECAIs; an INTERNAL rating is the firm's own IRB
      grade, so a flag on an internal row is ignored — removing it would strip
      the obligor's PD and model id (and let the parent's be inherited).
    - ``rating_incorporates_government_support`` is True. Null — no ECAI
      methodology review recorded — keeps the assessment (it is not treated as
      True; the column has no default on purpose).
    - The rated counterparty is an exposure-to-an-institution obligor: its
      ``entity_type`` maps to the ``institution`` SA class under ``pack``
      (bank / institution; a financial institution treated as an institution
      under Art. 119(5); a qualifying CCP, whose other exposures Art. 107(2)(a)
      treats "as exposures to an institution"), excluding a NON-qualifying CCP,
      which Art. 107(2)(b) treats "as exposures to a corporate" — the same
      ``is_qccp`` reading the classifier applies.
    - The counterparty is not ``is_government_owned_or_sponsored``.

    The filter acts on the ratings TABLE, not on a selected rating, because
    (g) shrinks the set Art. 138(1)(d)-(f) choose from: with a flagged CQS 2
    among CQS 1 / 2 / 3, the second-best rule picks 2 before the filter and the
    worse-of-two rule picks 3 after it, where nulling the selected rating would
    leave the institution unrated. It also runs before the per-agency "most
    recent" reduction in :func:`build_rating_inheritance_lazy`: where one
    agency publishes a support-uplifted and a stand-alone long-term assessment
    of the same bank, (g) bars only the first, so that agency's latest
    UNFLAGGED assessment is its assessment — reducing first would select the
    flagged row and then drop it, leaving the bank unrated. The consequence is
    that a ratings feed must not carry superseded assessments, or an agency's
    stale unflagged rating is revived. The resolver applies it once to the table
    both readers take — the long-term selection
    (:func:`build_rating_inheritance_lazy`) and the per-exposure short-term
    override (``enrich.apply_short_term_rating_override``) — and everything
    downstream (guarantor substitution, CCR rows, the output floor's SA
    equivalent) inherits the result through ``cqs``. The DQ015
    unsolicited-assessment count is also taken on the filtered table, so under
    Basel 3.1 a disregarded unsolicited assessment — one that is never used —
    is not counted.

    Out of scope here, by decision (P1.259): the firm-resolved single-value
    CQS carriers ``institution_cqs`` and collateral ``issuer_cqs`` carry no
    per-assessment rows and are taken as already Art. 138-compliant; and the
    Art. 139(6) higher-of for an exposure to an issue (P1.259b).
    """
    if ratings is None or not pack.feature("sa_implicit_support_ratings_disapplied"):
        return ratings

    logger.debug("PS1/26 Art. 138(1)(g): disregarding implicit-support assessments")
    in_scope = counterparties.filter(_art_138_1_g_obligor(pack)).select("counterparty_reference")
    # ECAI assessments only, matched exactly as the Art. 138 selection matches
    # them; eq_missing keeps both predicates two-valued, so no row is lost to null.
    flagged = pl.col("rating_type").eq_missing("external") & pl.col(
        "rating_incorporates_government_support"
    ).eq_missing(True)
    return pl.concat(
        [
            ratings.filter(flagged.not_()),
            ratings.filter(flagged).join(in_scope, on="counterparty_reference", how="anti"),
        ]
    )


def _art_138_1_g_obligor(pack: ResolvedRulepack) -> pl.Expr:
    """Counterparty predicate: an institution obligor (g) applies to, not exempt.

    ``entity_type`` is lowercased exactly as the classifier and the Art. 140(1)
    short-term gate lowercase it; a null type matches nothing (kept). The
    exemption flag defaults to False at the loader, and ``eq_missing`` keeps a
    stray null from opening the carve-out.
    """
    institution_types = entity_types_by_sa_class(pack).get(ExposureClass.INSTITUTION.value, ())
    entity_type = pl.col("entity_type").str.to_lowercase()
    non_qualifying_ccp = entity_type.eq_missing("ccp") & pl.col("is_qccp").eq_missing(False)
    government_owned = pl.col("is_government_owned_or_sponsored").eq_missing(True)
    return (
        entity_type.is_in(institution_types) & non_qualifying_ccp.not_() & government_owned.not_()
    )
