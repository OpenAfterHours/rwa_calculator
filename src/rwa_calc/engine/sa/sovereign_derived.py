"""
CQS-keyed risk-weight table lookups for the Standardised Approach.

Pipeline position:
    CRMProcessor -> SACalculator (engine/sa/risk_weights.py) -> OutputAggregator
    Called from the CRR / Basel 3.1 class-override chains to price a row off a
    CQS-keyed regulatory table.

Key responsibilities:
- ``sovereign_derived_rw_expr``: price a row off ``cp_sovereign_cqs`` — the
  counterparty's home central government's credit quality step — for the three
  classes the CRR derives from their sovereign when they carry no rating of
  their own (unrated PSE, unrated non-domestic RGLA, unrated institution and,
  via Art. 117(1), unrated non-named MDB).
- ``cqs_table_lookup_expr``: the same shape parameterised on the source CQS
  column, so it can drive any CQS-keyed table off ``cqs`` or a lifted variant.
- ``crr_art_121_4_trade_finance_expr``: the Art. 121(4) trade-finance predicate
  that holds those exposures — trade finance with a residual maturity of up to
  one year — out of the Art. 121(1) Table 5 ladder.

Both lookups are **RW-valued**: they map a CQS to a risk weight directly rather
than lifting a CQS into ``cqs``. That is deliberate — ``cp_sovereign_cqs`` is
``Int32`` while ``cqs`` is ``Int8``, and a lift that forgets the cast widens the
result until the sealed ``sa_branch`` edge contract rejects it (see the dtype
note in ``engine/sa/cqs_lift.py``).

References:
- CRR Art. 115(1)(a) Table 1A: sovereign-derived RGLA risk weights
- CRR Art. 116(1) Table 2: sovereign-derived PSE risk weights
- CRR Art. 121(1) Table 5: sovereign-derived unrated-institution risk weights
- CRR Art. 121(2): unrated central government -> 100%
- CRR Art. 121(4); CRR Art. 162(3) second subparagraph point (b): trade-finance
  exposures to unrated institutions, residual maturity of up to one year
- CRR Art. 117(1): non-named MDBs risk-weighted as institutions
- PRA PS1/26 Art. 115 / 116 (identical sovereign-derived values)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.domain.enums import CQS
from rwa_calc.engine.utils import exact_fractional_years_expr

if TYPE_CHECKING:
    from datetime import date
    from decimal import Decimal

logger = logging.getLogger(__name__)

# The rated span of every CQS-keyed regulatory table. UNRATED is deliberately
# absent: each caller supplies its own unrated fallback, because the article
# that defines it differs by class (Art. 121(2) for institutions, Art. 116(1)
# for PSEs, Art. 122(2) for corporates).
_RATED_CQS: tuple[CQS, ...] = (CQS.CQS1, CQS.CQS2, CQS.CQS3, CQS.CQS4, CQS.CQS5, CQS.CQS6)


def sovereign_derived_rw_expr(
    table: dict[CQS, Decimal],
    unrated_default: float,
) -> pl.Expr:
    """Build a Polars expression pricing a row off its home sovereign's CQS.

    Used for unrated PSEs (Art. 116(1) Table 2), unrated non-domestic RGLAs
    (Art. 115(1)(a) Table 1A) and unrated institutions (Art. 121(1) Table 5,
    reached directly and via the Art. 117(1) non-named-MDB redirect). All three
    tables map sovereign CQS 1-6 to a risk weight; when ``cp_sovereign_cqs`` is
    null or out of domain the conservative ``unrated_default`` applies.

    That fallback is what implements CRR Art. 121(2) on the institution path —
    "for exposures to unrated institutions incorporated in countries where the
    central government is unrated, the risk weight shall be 100%" — so callers
    must not add a null gate of their own in front of it.

    References:
        CRR Art. 115(1)(a) Table 1A / Art. 116(1) Table 2 / Art. 121(1) Table 5
        CRR Art. 121(2) — the unrated-central-government residual
        PRA PS1/26 Art. 115 / 116 (identical values)
    """
    return cqs_table_lookup_expr("cp_sovereign_cqs", table, unrated_default)


def cqs_table_lookup_expr(
    cqs_col: str,
    table: dict[CQS, Decimal],
    unrated_default: pl.Expr | float,
) -> pl.Expr:
    """Build a when/then chain mapping a CQS-bearing column to RW from a CQS table.

    Parameterised on the CQS source column so it can drive any CQS-keyed
    regulatory table (CGCB Art. 114, MDB Table 2B Art. 117(1), PSE Table 2A
    Art. 116(2), RGLA Table 1B Art. 115(1)(b), Corporate Art. 122). The caller
    controls the unrated fallback, as a constant or a Polars expression.
    """
    expr = pl.when(pl.col(cqs_col) == int(_RATED_CQS[0])).then(pl.lit(float(table[_RATED_CQS[0]])))
    for cqs_val in _RATED_CQS[1:]:
        expr = expr.when(pl.col(cqs_col) == int(cqs_val)).then(pl.lit(float(table[cqs_val])))
    if isinstance(unrated_default, pl.Expr):
        return expr.otherwise(unrated_default)
    return expr.otherwise(pl.lit(unrated_default))


@cites("CRR Art. 121")
@cites("CRR Art. 162(3)")
def crr_art_121_4_trade_finance_expr(reporting_date: date, max_residual_years: float) -> pl.Expr:
    """Art. 121(4) trade-finance exposures to unrated institutions.

    Art. 121(4) prescribes 50% (20% where residual maturity is three months or
    less), "Notwithstanding paragraphs 2 and 3", for "trade finance exposures
    referred to in point (b) of the second subparagraph of Article 162(3)".
    Point (b) is "self-liquidating short-term trade finance transactions
    connected to the exchange of goods or services with a residual maturity of
    up to one year". So the population is a trade-LC-flagged row whose RESIDUAL
    maturity is at most ``max_residual_years`` (the CRR pack's
    ``sa_unrated_institution_trade_finance_max_residual_maturity_years``,
    inclusive). A flagged row with longer to run is not an Art. 121(4)
    exposure: Table 5 governs it like any other unrated institution.

    The residual is the supplied ``residual_maturity_years``, else the years
    from ``reporting_date`` to ``maturity_date`` on the same day count as the
    IRB Art. 162(3) one-day-floor derivation. Pipeline exposure rows carry
    ``residual_maturity_years`` as null (it is a collateral-schema column), so
    the date derivation is the production path, not a fallback. A row with
    neither stays IN scope: it is not shown to fall outside point (b).

    Neither Art. 121(4) rate is implemented (P1.326 / P1.338 / P7.8), so
    in-scope rows are held OUT of the ladder and land on the Art. 121 unrated
    **100%** residual via the base CQS join. That interim over-states the
    purposive reading (a 50% trade-finance rate). It is NOT conservative on the
    literal reading ("Notwithstanding paragraphs 2 and 3", not 1, so Table 5
    still governs): at sovereign CQS 6 that gives 150%. Settling the reading is
    P1.338's; do not add a rate branch on the strength of this docstring.

    Keyed on RESIDUAL maturity, never original: the one-year condition on the
    sibling PS1/26 Art. 121(6)(b) floor exemption is on ORIGINAL maturity and
    is a different rule. ``eq_missing`` and the ``is_null`` arm keep the
    predicate null-safe without a ``fill_null`` site — a negated Kleene null
    would silently drop rows from the ladder.
    """
    residual = pl.coalesce(
        pl.col("residual_maturity_years"),
        exact_fractional_years_expr(reporting_date, "maturity_date"),
    )
    within_point_b = residual.is_null() | (residual <= max_residual_years)
    return pl.col("is_short_term_trade_lc").eq_missing(True) & within_point_b
