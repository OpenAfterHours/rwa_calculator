"""
Group-wide obligor aggregates for solo and sub-consolidated runs.

Pipeline position:
    resolve_scope (GROUP_POPULATION) -> hierarchy_resolver (this module, via the
    stage adapter) -> classifier (retail threshold) / calculators (Art. 501 E*)

Key responsibilities:
- ``whole_group_increments``: from the run's own hierarchy-resolved exposures
  and the same resolution of the WHOLE reporting group's population, publish
  per obligor-group key what the rest of the group adds over the run's own
  books — to the retail-threshold aggregate (``exposure_for_retail_threshold``,
  net of residential cover) and to the Art. 501 E* (drawn + interest, net of
  residential cover). Each increment is ``max(whole group - own books, 0)``:
  both sides are measured with the same hierarchy rules (FX, facility and
  counterparty-level collateral allocation), so a pledge whose exposures span
  the scope boundary is allocated as the whole-group run allocates it, and the
  increment can only add.
- ``attach_out_of_scope_threshold``: carry the threshold increment onto the
  run's exposures as ``out_of_scope_group_adjusted_exposure`` — the classifier
  adds it to ``lending_group_adjusted_exposure`` for the threshold test only.

Why: the retail threshold and E* count debt owed to the whole banking group,
not only to the reporting entity (CRR Art. 123(c), 501(1); PS1/26
Art. 123(1)(b)(ii), 123A(1)(b)(ii), 147(5)(a)(ii)). The scope stage filters the
lending frames before the hierarchy sums them, so without this a solo run saw
only its own books and could treat a GBP 1.2m obligor as GBP 600k retail.

The Art. 123A granularity limb keeps reading the run's own
``lending_group_adjusted_exposure``: it measures the reporting entity's retail
portfolio, which the group-wide amount owed does not change.

Limitations:
- Only lending exposures (loans, contingents, facilities) of the OTHER group
  entities are counted — their CCR / SFT exposures are not run through the
  group pass. Under CRR Art. 501, E* of an unscoped run includes the drawn
  amount of any CCR row; a solo run's E* omits other entities' CCR rows.
- Group entities whose books are not in the feed cannot be counted (CRR
  Art. 123(c) "to the knowledge of the institution").

References:
- CRR Art. 123(c): retail threshold, "owed to the institution and parent
  undertakings and its subsidiaries"
- CRR Art. 501(1): E*, "owed to the institution, its subsidiaries, its parent
  undertakings and other subsidiaries of those parent undertakings"
- PRA PS1/26 Art. 123(1)(b)(ii) / 123A(1)(b)(ii) / 147(5)(a)(ii): "owed to the
  institution, its parent undertakings, its subsidiaries and subsidiaries of
  its parent undertakings"
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

from rwa_calc.contracts.edges import HIERARCHY_RESOLVED_EDGE
from rwa_calc.engine.materialise import materialise_frame
from rwa_calc.engine.supporting_factors import (
    OBLIGOR_GROUP_KEY,
    e_star_contribution_expr,
    obligor_group_key_expr,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Main entry point
# =============================================================================


@cites("CRR Art. 123")
@cites("CRR Art. 501")
@cites("PS1/26, paragraph 123A")
def whole_group_increments(
    own_books: pl.LazyFrame,
    whole_group: pl.LazyFrame,
) -> pl.LazyFrame:
    """Per obligor-group key, what the rest of the reporting group adds.

    Args:
        own_books: The run's hierarchy-resolved exposures (scoped population).
        whole_group: The same resolution of the whole reporting group's
            population (``GROUP_POPULATION``).

    Returns:
        A materialised frame, one row per obligor-group key the run holds AND
        the group pass saw: ``obligor_group_key``, ``group_threshold_increment``
        (retail threshold, net of residential cover) and
        ``group_e_star_increment`` (Art. 501 E*), each ``max(whole - own, 0)``.
        Materialised once because two stages read it (the hierarchy's threshold
        column and the calculators' E*) and its plan is a whole hierarchy pass.
    """
    whole = _key_totals(whole_group, "whole")
    own = _key_totals(own_books, "own")
    increments = whole.join(own, on=OBLIGOR_GROUP_KEY, how="inner").select(
        pl.col(OBLIGOR_GROUP_KEY),
        (pl.col("_threshold_whole") - pl.col("_threshold_own"))
        .clip(lower_bound=0.0)
        .alias("group_threshold_increment"),
        (pl.col("_e_star_whole") - pl.col("_e_star_own"))
        .clip(lower_bound=0.0)
        .alias("group_e_star_increment"),
    )
    logger.debug("hierarchy: whole-group obligor increments computed for a scoped run")
    return materialise_frame(increments)


def attach_out_of_scope_threshold(
    exposures: pl.LazyFrame, increments: pl.LazyFrame
) -> pl.LazyFrame:
    """Add ``out_of_scope_group_adjusted_exposure`` from the threshold increments.

    The retail-threshold amount (net of residential cover) the obligor or its
    lending group owes to the reporting group's OTHER entities, broadcast to
    every row of the key. Null where the group pass did not see the key (an
    intragroup row kept on an individual run): nothing is owed elsewhere.
    Replaces the typed-null column the hierarchy producer seal declares.
    """
    return (
        exposures.drop("out_of_scope_group_adjusted_exposure", strict=False)
        .join(
            increments.select(
                pl.col(OBLIGOR_GROUP_KEY).alias("_obligor_group_key"),
                pl.col("group_threshold_increment").alias("out_of_scope_group_adjusted_exposure"),
            ),
            left_on=obligor_group_key_expr(),
            right_on="_obligor_group_key",
            how="left",
            maintain_order="left",
        )
        .drop("_obligor_group_key", strict=False)
    )


# =============================================================================
# Private helpers
# =============================================================================


def _key_totals(exposures: pl.LazyFrame, side: str) -> pl.LazyFrame:
    """Sum both group measures per obligor-group key on one side of the comparison.

    Rows with a null key (no counterparty) form no group and are dropped, as the
    windowed sums elsewhere treat a null key as its own single-row obligor.
    """
    return (
        exposures.with_columns(obligor_group_key_expr().alias(OBLIGOR_GROUP_KEY))
        .filter(pl.col(OBLIGOR_GROUP_KEY).is_not_null())
        .group_by(OBLIGOR_GROUP_KEY)
        .agg(
            pl.col("exposure_for_retail_threshold").sum().alias(f"_threshold_{side}"),
            e_star_contribution_expr(HIERARCHY_RESOLVED_EDGE.columns)
            .sum()
            .alias(f"_e_star_{side}"),
        )
    )
