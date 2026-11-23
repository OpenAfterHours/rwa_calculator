"""
Payroll / pension loan qualification for the SA retail 35% risk weight.

Pipeline position:
    CRMProcessor -> SACalculator -> Aggregation
    (read by ``engine/sa/risk_weights.py``: the maturity test is evaluated in
    ``_prepare_risk_weight_lookup`` and the 35% gate in both regimes' retail
    branches)

Key responsibilities:
- ``payroll_maturity_over_cap_expr``: True where the row's OWN maturity data
  shows an original maturity above the cap in condition (d), "the maximum
  original maturity of the loan is equal to or less than 10 years".
- ``payroll_loan_35pct_expr``: the retail payroll / pension 35% gate -- the
  caller-attested ``is_payroll_loan`` flag, withheld where condition (d) is
  contradicted.

Attestation model. Both regimes assign the 35% "provided that all the following
conditions are met": (a) an unconditional authority to deduct the monthly
payments from the pension or salary, (b) insurance cover for death, inability to
work, unemployment or a fall in the net pension or salary, (c) payments on all
such loans at most 20% of the net monthly pension or salary, and (d) the
10-year maximum original maturity. The engine has no input for (a)-(c); the flag
is the firm's attestation of all four. Condition (d) is the one the row's own
data can contradict, so the engine checks for that contradiction and nothing
more: where no maturity data is present the attestation stands.

The test is "contradicted if EITHER source shows more than the cap":

- ``value_date`` and ``maturity_date`` both present: fails where
  ``maturity_date`` falls after ``value_date`` plus the cap in calendar months.
  "Equal to or less than 10 years" is a calendar bound, and no day-count
  threshold can express it: 2027-01-15 -> 2037-01-15 (exactly 10 years) and
  2026-01-15 -> 2036-01-16 (10 years and a day) both span 3,653 days. The SA
  stage's own ``(maturity_date - value_date) / 365`` derivation puts every
  exactly-10-year term above 10.0, so it must not be compared with the cap.
- a supplied ``original_maturity_years``: fails where it exceeds the cap
  (strict ``>``, so an explicit 10.0 meets the bound).

That is why the test reads the frame BEFORE ``_prepare_risk_weight_lookup``
back-fills ``original_maturity_years`` from the dates: after the back-fill a
supplied figure and a derived one cannot be told apart.

Reach of the second limb. Loan input has no ``original_maturity_years`` column,
and the facility input's one does not survive the stage edges before SA, so in a
pipeline run the check sees the dates only; the supplied-figure limb serves
direct ``calculate_branch`` callers. A payroll facility that states only an
explicit original maturity over the cap, with no dates, therefore keeps the 35%
-- an open residual, not closed here.

Why a module of its own: ``risk_weights.py`` sits at the
``max_engine_module_loc`` ratchet, and the two regimes' retail chains must read
one predicate so the 35% cannot be gated differently by regime.

References:
- PRA PS1/26 Art. 123(4)(a)-(d): payroll / pension loans, 35%, all four conditions
- CRR Art. 123 final subparagraph points (a)-(d) (inserted by Reg. (EU) 2019/876)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

if TYPE_CHECKING:
    from rwa_calc.rulebook.resolve import ResolvedRulepack

logger = logging.getLogger(__name__)

#: Temporary column carrying the condition (d) test from the risk-weight setup
#: (before the maturity back-fill) to the retail branches; dropped at cleanup.
PAYROLL_MATURITY_OVER_CAP_COL = "_payroll_maturity_over_cap"
_CAP_ENTRY = "retail_payroll_loan_max_original_maturity_years"


@cites("CRR Art. 123")
@cites("PS1/26, paragraph 123")
def payroll_loan_35pct_expr() -> pl.Expr:
    """True where a retail row takes the 35% payroll / pension loan weight.

    The flag attests conditions (a)-(d) of PS1/26 Art. 123(4) / the CRR
    Art. 123 final subparagraph; the row is denied the 35% where its own
    maturity data contradicts condition (d). Reads
    ``PAYROLL_MATURITY_OVER_CAP_COL``, which ``payroll_maturity_over_cap_expr``
    produces, so the caller must have added that column first.

    Returns:
        Boolean expression, never null.
    """
    return pl.col("is_payroll_loan").fill_null(False) & ~pl.col(PAYROLL_MATURITY_OVER_CAP_COL)


@cites("CRR Art. 123")
@cites("PS1/26, paragraph 123")
def payroll_maturity_over_cap_expr(pack: ResolvedRulepack) -> pl.Expr:
    """True where the row's own data shows an original maturity above the cap.

    Condition (d): "the maximum original maturity of the loan is equal to or
    less than 10 years" (PS1/26 Art. 123(4)(d); CRR Art. 123 final subparagraph
    point (d), "ten years"). The cap is the resolved pack's
    ``retail_payroll_loan_max_original_maturity_years``.

    Must be evaluated on the frame as supplied, before
    ``original_maturity_years`` is back-filled from the dates (see the module
    docstring). Every term is null-safe without a ``fill_null``: an absent date
    or figure is "no evidence", never a contradiction.

    Args:
        pack: The run's resolved rulepack.

    Returns:
        Boolean expression aliased ``PAYROLL_MATURITY_OVER_CAP_COL``, never null.

    Raises:
        ValueError: if the pack's cap is not a whole number of months (a pack
            authoring error, not a data-quality one).
    """
    cap_years = pack.scalar(_CAP_ENTRY)
    cap_months = int(cap_years * 12)
    if cap_months != cap_years * 12:
        msg = f"{_CAP_ENTRY} = {cap_years} is not a whole number of months"
        raise ValueError(msg)
    value_date = pl.col("value_date")
    maturity_date = pl.col("maturity_date")
    dates_over_cap = (
        value_date.is_not_null()
        & maturity_date.is_not_null()
        & (maturity_date > value_date.dt.offset_by(f"{cap_months}mo"))
    )
    stated_over_cap = pl.col("original_maturity_years").is_not_null() & (
        pl.col("original_maturity_years") > float(cap_years)
    )
    return (dates_over_cap | stated_over_cap).alias(PAYROLL_MATURITY_OVER_CAP_COL)
