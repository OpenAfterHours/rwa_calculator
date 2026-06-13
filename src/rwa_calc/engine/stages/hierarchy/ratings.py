"""
Dual rating-inheritance resolution for the hierarchy stage.

Pipeline position:
    Loader -> HierarchyResolver (stages/hierarchy) -> Classifier
    Sub-module of the hierarchy stage package; consumed by ``graph`` when
    building the sealed CounterpartyLookup.

Key responsibilities:
- Resolve the best internal rating (PD) and best external rating (CQS)
  separately per counterparty (dual per-type resolution).
- Combine multiple external assessments per CRR Art. 138 (second-best rule).
- Inherit internal ratings from the ultimate parent when the entity has no
  own internal rating; external ratings are never inherited.

References:
- CRR Art. 135: Use of external credit assessments (ECAIs)
- CRR Art. 136: Mapping of ECAI ratings to credit quality steps
- CRR Art. 138: Issuer / issue credit assessment
- CRR Art. 171(1) / Art. 175(3): internal rating assignment within groups
"""

from __future__ import annotations

import logging

import polars as pl

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
