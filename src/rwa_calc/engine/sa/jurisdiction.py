"""
Jurisdiction-eligibility predicates for Standardised Approach risk weighting.

Several SA treatments are available only to UK counterparties, or to
third-country counterparties whose jurisdiction carries an affirmative HM
Treasury equivalence determination. This module holds those jurisdiction gates
as plain typed Polars predicates so the risk-weight override chains in
``engine/sa/risk_weights.py`` read as one-line branches.

Pipeline position:
    CRMProcessor -> SACalculator (engine/sa/risk_weights.py) -> Aggregation

Key responsibilities:
- CRR Art. 116(5): third-country PSE supervisory-equivalence gate, whose
  residual is a flat 100% risk weight.
- CRR Art. 116(3) / PS1/26 Art. 116(3): the short-term 20% PSE preferential,
  which is available to UK PSEs only.

The two PSE predicates here are DISTINCT and both are needed:
  (a) ``pse_jurisdiction_not_permitted_expr`` — a third-country PSE with no
      Treasury equivalence determination takes a flat 100%, suppressing every
      Art. 116 treatment;
  (b) ``pse_short_term_eligible_expr`` — the Art. 116(3) 20% is available to UK
      PSEs only, so an *equivalent* third-country PSE with a short original
      maturity still falls through to its Table 2 / Table 2A weight rather than
      taking the 20%.

Branch ordering in the override chains is LOAD-BEARING: the Art. 116(5) gate
must be evaluated BEFORE any other PSE branch, because its flat 100% has to
suppress all three PSE treatments — the Art. 116(3) short-term 20%, the
Art. 116(1) Table 2 sovereign-derived lookup, and the Art. 116(2) Table 2A
own-rating weight that a PSE row would otherwise pick up from the CQS join by
falling through the chain.

Null-VALUE convention shared by every predicate here: a null jurisdiction
attribute is never read as satisfying a gate. Equivalence is an affirmative
determination, so an absent assertion cannot manufacture one, and each
predicate collapses nulls to a definite Boolean rather than letting a Kleene
null fall through the enclosing ``when`` — falling through would silently grant
the preferential treatment, the anti-conservative direction.

References:
- CRR Art. 116(5): third-country PSE equivalence + 100% residual
- PRA PS1/26 Art. 116(1)-(3) (UK-scoped) and Art. 116(3A) (third-country
  redirect "for the purpose of Article 116(5) of CRR")
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

logger = logging.getLogger(__name__)


@cites("CRR Art. 116(5)")
@cites("PS1/26, paragraph 116")
def pse_jurisdiction_not_permitted_expr() -> pl.Expr:
    """Art. 116(5) third-country PSE jurisdiction gate (True = blocked).

    CRR Art. 116(5): a third-country PSE may take the Art. 116(1)/(2)
    treatments only where the Treasury has determined that the jurisdiction
    "applies supervisory and regulatory arrangements at least equivalent to
    those applied in the United Kingdom"; "Otherwise the institutions shall
    apply a risk weight of 100 %".

    Two limbs are permitted (predicate returns False):
      - a UK PSE — Art. 116(1)-(3) apply directly and the equivalence flag is
        never consulted, because a UK PSE is not a third-country PSE;
      - a third-country PSE whose ``cp_is_equivalent_jurisdiction`` is True.

    Regime-invariant, so there is no pack Feature and no regime branch: PS1/26
    Art. 116 scopes paragraphs 1-3 to "UK public sector entities" and admits
    third-country PSEs only via Art. 116(3A) "[f]or the purpose of Article
    116(5) of CRR", recording Art. 116(5) itself as "[Note: Provision not in
    PRA Rulebook]" because the Treasury equivalence power stays in CRR.

    References:
        CRR Art. 116(5); PRA PS1/26 Art. 116(1)-(3) and Art. 116(3A)
    """
    # ``is_not_null() &`` on both limbs: a null country code cannot prove
    # UK-ness (the convention used by the model-permission geography filter in
    # engine/stages/classify/permissions.py) and a null flag is not an
    # assertion. See the module docstring for why nulls must not stay Kleene.
    #
    # The ``cast`` calls are load-bearing, not cosmetic: a frame whose column is
    # entirely null carries Polars dtype ``Null`` rather than String/Boolean, and
    # ``Null`` propagates through the comparison and the ``|`` so that the final
    # ``~`` raises "dtype Null not supported in 'not' operation". Casting pins
    # both operands to their declared dtype so an all-null column degrades to a
    # clean False instead of blowing up. This is a dtype coercion, NOT a null
    # fill — the null-VALUE semantics stay with ``is_not_null()`` above.
    equivalent = pl.col("cp_is_equivalent_jurisdiction").cast(pl.Boolean)
    equivalence_asserted = equivalent.is_not_null() & equivalent
    return ~(_is_uk_counterparty_expr() | equivalence_asserted)


@cites("CRR Art. 116(3)")
@cites("PS1/26, paragraph 116")
def pse_short_term_eligible_expr(short_term_threshold_years: float) -> pl.Expr:
    """Art. 116(3) short-term PSE eligibility — UK PSEs only (True = 20% applies).

    Art. 116(3) grants a flat 20% to PSE exposures "with an original maturity of
    three months or less". Two conditions, both required:

    1. **Jurisdiction — UK only.** PS1/26 Art. 116(3) reads "exposures to **UK**
       public sector entities", and Art. 116(3A) redirects "UK public sector
       entities" to mean third-country PSEs **for paragraphs 1 and 2 only** —
       paragraph 3 keeps its literal UK scope. CRR Art. 116(5) points the same
       way: a third-country PSE may be weighted in the same manner only "in
       accordance with paragraph 1 or 2". So an *equivalent* third-country PSE
       still falls through to its Table 2 / Table 2A weight and does NOT take
       the 20%; a *non-equivalent* one is already caught by
       ``pse_jurisdiction_not_permitted_expr``. This is the conservative reading
       under both regimes and is mandated outright under Basel 3.1 — a 20%
       against a Table 2/2A weight of 50%, 100% or 150% is a material
       understatement, and splitting the regimes here would leave an
       anti-conservative divergence on the same population.
    2. **ORIGINAL maturity**, not residual — a seasoned long-dated PSE bond with
       a short residual does not qualify.

    Args:
        short_term_threshold_years: the "three months or less" bound in years,
            passed by the caller so the numeric stays with the risk-weight
            chain rather than being declared at this module's scope.
    """
    original_maturity = pl.col("original_maturity_years")
    return (
        _is_uk_counterparty_expr()
        & original_maturity.is_not_null()
        & (original_maturity <= short_term_threshold_years)
    )


def _is_uk_counterparty_expr() -> pl.Expr:
    """True only where ``cp_country_code`` is definitely ``GB``.

    A null country code cannot prove UK-ness, so ``is_not_null() &`` collapses
    it to a definite False. Do NOT "simplify" this to a bare ``== "GB"``: that
    yields a Kleene null for a null code, which would propagate through the
    callers' ``|`` / ``~`` and let the enclosing ``when`` fall through to the
    preferential PSE treatments — the anti-conservative direction.
    """
    country = pl.col("cp_country_code").cast(pl.String)
    return country.is_not_null() & (country == "GB")
