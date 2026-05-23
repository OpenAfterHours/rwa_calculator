"""
Per-trade adjusted notional for SA-CCR (interest-rate asset class).

Pipeline position:
    Classifier -> CCRCalculator (adjusted notional) -> ...

Key responsibilities:
- Compute the interest-rate adjusted notional ``d_i`` per CRR Art. 279b(1)(a),
  i.e. the trade notional scaled by the supervisory duration factor
  ``SD(S, E) = (exp(-0.05*S) - exp(-0.05*E)) / 0.05`` where ``S`` is the
  years-to-start floored at 10 business days (= 10/250 = 0.04y) and ``E`` is
  the years-to-maturity.

References:
- CRR Art. 279b(1)(a): Adjusted notional amount (IR)
- BCBS CRE52.40: 250-business-day year convention for the start-date floor
"""

from __future__ import annotations

import logging
from datetime import date

import polars as pl
from watchfire import cites

from rwa_calc.data.tables.sa_ccr_factors import (
    SA_CCR_BUSINESS_DAYS_PER_YEAR,
    SA_CCR_START_FLOOR_YEARS,
    SA_CCR_SUPERVISORY_DURATION_RATE,
)

logger = logging.getLogger(__name__)


# Watchfire's bundled CRR index does not yet contain Art. 279b; collapse the
# ``@cites`` to the parent Art. 279 and preserve sub-article attribution in the
# docstring (mirrors the P8.7 fix-commit pattern for Art. 280a/b/c).
@cites("CRR Art. 279")
def compute_adjusted_notional_ir(
    trades: pl.LazyFrame,
    reporting_date: date,
) -> pl.LazyFrame:
    """SA-CCR adjusted notional for interest-rate trades per CRR Art. 279b(1)(a).

    For ``asset_class == "interest_rate"``:

        d = notional * SD(S, E)
        SD(S, E) = (exp(-0.05*S) - exp(-0.05*E)) / 0.05

    where ``S`` is the years-to-start floored at 10 business days
    (10/250 = 0.04y) and ``E`` is the years-to-maturity. FX / credit / equity
    / commodity branches return null (deferred to subsequent batches).

    Args:
        trades: LazyFrame at trade grain with columns ``asset_class``,
            ``notional``, ``start_date``, ``maturity_date``.
        reporting_date: As-of date for the calculation; used to compute the
            year fractions ``S`` (start) and ``E`` (maturity).

    Returns:
        The input LazyFrame with a new ``adjusted_notional: Float64`` column;
        null for non-IR rows.

    References:
        - CRR Art. 279b(1)(a)
        - BCBS CRE52.40 (footnote: 250-business-day year for the start floor)
    """
    rate = float(SA_CCR_SUPERVISORY_DURATION_RATE)
    s_floor = float(SA_CCR_START_FLOOR_YEARS)
    # SA_CCR_BUSINESS_DAYS_PER_YEAR is referenced as the basis of the derived
    # ``s_floor`` constant; touching it here keeps the import meaningful.
    _ = SA_CCR_BUSINESS_DAYS_PER_YEAR

    # Calendar-day -> year fraction. 365.25 is the standard SA-CCR convention
    # for year fractions; the 250-business-day year applies only to the
    # 10-BD start-date floor, which is pre-computed into ``s_floor`` above.
    years_to_start = (pl.col("start_date") - pl.lit(reporting_date)).dt.total_days() / 365.25
    years_to_maturity = (pl.col("maturity_date") - pl.lit(reporting_date)).dt.total_days() / 365.25

    # S floored at 10 BD = 10/250 = 0.04y per Art. 279b(1)(a).
    s_floored = pl.max_horizontal(years_to_start, pl.lit(s_floor))

    # SD(S, E) = (exp(-rate*S) - exp(-rate*E)) / rate
    sd = ((-rate * s_floored).exp() - (-rate * years_to_maturity).exp()) / rate
    d = pl.col("notional") * sd

    return trades.with_columns(
        pl.when(pl.col("asset_class") == "interest_rate")
        .then(d)
        .otherwise(pl.lit(None, dtype=pl.Float64))
        .alias("adjusted_notional")
    )
