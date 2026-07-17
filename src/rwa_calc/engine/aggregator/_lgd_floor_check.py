"""
Portfolio-level A-IRB retail real-estate LGD-floor backstop (CRR Art. 164(4)/(5)).

Internal module — not part of the public API.

Pipeline position:
    IRB/SA/Slotting Calculators -> OutputAggregator (this check) -> AggregatedResultBundle

Key responsibilities:
- After the per-approach results are merged, compute the EAD-weighted-average
  own-estimate LGD of the A-IRB retail real-estate book, split into the
  residential (10%) and commercial (15%) sub-portfolios, and emit ONE
  monitoring WARNING (IRB007) per sub-portfolio whose average falls below its
  Art. 164(4) floor. The check never mutates RWA, LGD, or EAD — under CRR
  Art. 164(4) this is a portfolio-level monitoring floor, not a capital add-on.
- Art. 164(4): exposures guaranteed by a central government are excluded from
  the average — the guarantee substitutes a 0%-RW obligor, so the A-IRB
  own-estimate LGD is not the binding parameter on that leg.

CRR-only: gated by the ``crr_retail_re_portfolio_lgd_floor`` pack Feature. Basel
3.1 disables it — its per-exposure ``airb_lgd_floor`` already floors each
retail-RE LGD before it reaches the aggregator.

References:
- CRR Art. 164(4): residential 10% / commercial 15% portfolio EW-avg LGD floor.
- CRR Art. 164(4): central-government-guarantee exclusion from the floor.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.errors import ERROR_RETAIL_RE_PORTFOLIO_LGD_FLOOR, CalculationError
from rwa_calc.domain.enums import ErrorCategory, ErrorSeverity

if TYPE_CHECKING:
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)


@cites("CRR Art. 164")
def check_retail_re_portfolio_lgd_floors(
    combined: pl.DataFrame,
    pack: ResolvedRulepack,
) -> list[CalculationError]:
    """Return one IRB007 WARNING per A-IRB retail-RE sub-portfolio below its LGD floor.

    ``combined`` is the aggregator's already-materialised merged per-approach
    results frame (``combined_df``) — reused so no extra collect is needed. The
    population is the A-IRB retail-mortgage book minus central-government-
    guaranteed legs (Art. 164(4)); it is split into residential
    (``property_type != "commercial"``, null -> residential) and commercial
    (``property_type == "commercial"``) sub-portfolios, and each is tested for
    EAD-weighted-average own-estimate LGD below its floor (residential 10% /
    commercial 15%, read from the resolved pack). An empty sub-portfolio or a
    zero total EAD raises no warning, so at most two warnings are returned.
    """
    # Columns the population predicate and the EW-avg aggregation require. When
    # any is absent the check is skipped (returns no warnings) rather than
    # raising, so it stays inert on frames without the A-IRB/guarantee
    # provenance columns. Kept function-local — these are internal result-frame
    # column names, not a validation string-enum for data/schemas.py.
    required_columns = (
        "is_airb",
        "exposure_class",
        "property_type",
        "lgd",
        "ead_final",
        "is_guaranteed",
        "guarantor_exposure_class",
    )
    if not set(required_columns) <= set(combined.columns):
        return []

    resi_floor = float(pack.scalar("retail_residential_re_portfolio_lgd_floor"))
    comm_floor = float(pack.scalar("retail_commercial_re_portfolio_lgd_floor"))

    # Art. 164(4) population: A-IRB retail mortgages, minus the Art. 164(4)
    # central-government-guarantee carve-out (that leg substitutes a 0%-RW
    # obligor, so its own-estimate LGD is not the binding floor input).
    in_population = (
        pl.col("is_airb")
        & (pl.col("exposure_class") == "retail_mortgage")
        & ~(
            pl.col("is_guaranteed")
            & (pl.col("guarantor_exposure_class") == "central_govt_central_bank")
        )
    )
    # Residential vs commercial bucket; a null property_type falls to residential.
    bucket = (
        pl.when(pl.col("property_type") == "commercial")
        .then(pl.lit("commercial"))
        .otherwise(pl.lit("residential"))
    )

    # Eager group_by/agg on the already-materialised frame (no new collect).
    per_bucket = (
        combined.filter(in_population)
        .with_columns(bucket.alias("_re_bucket"))
        .group_by("_re_bucket")
        .agg(
            (pl.col("lgd") * pl.col("ead_final")).sum().alias("_lgd_ead"),
            pl.col("ead_final").sum().alias("_ead"),
            pl.len().alias("_n"),
        )
    )

    floors = {"residential": resi_floor, "commercial": comm_floor}
    warnings: list[CalculationError] = []
    for row in per_bucket.iter_rows(named=True):
        total_ead = row["_ead"] or 0.0
        if total_ead <= 0.0:
            continue
        ew_avg_lgd = row["_lgd_ead"] / total_ead
        floor = floors[row["_re_bucket"]]
        if ew_avg_lgd < floor:
            warnings.append(
                _portfolio_lgd_floor_warning(
                    row["_re_bucket"], ew_avg_lgd, floor, total_ead, int(row["_n"])
                )
            )
    return warnings


def _portfolio_lgd_floor_warning(
    bucket: str,
    ew_avg_lgd: float,
    floor: float,
    total_ead: float,
    count: int,
) -> CalculationError:
    """Build the IRB007 monitoring warning for one breaching sub-portfolio."""
    return CalculationError(
        code=ERROR_RETAIL_RE_PORTFOLIO_LGD_FLOOR,
        message=(
            f"A-IRB {bucket} real-estate retail portfolio EAD-weighted-average "
            f"own-estimate LGD {ew_avg_lgd:.2%} is below the CRR Art. 164(4) floor "
            f"of {floor:.0%} (total EAD {total_ead:,.0f} across {count} "
            f"exposure(s)); Art. 164(4) is a portfolio-level monitoring floor, so "
            f"no RWA or LGD adjustment is applied."
        ),
        severity=ErrorSeverity.WARNING,
        category=ErrorCategory.DATA_QUALITY,
        field_name="lgd",
        regulatory_reference="CRR Art. 164(4)",
    )
