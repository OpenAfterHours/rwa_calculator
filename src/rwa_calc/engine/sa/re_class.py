"""
Real-estate class predicates shared by the SA risk-weight dispatchers.

Pipeline position:
    CRMProcessor -> SACalculator -> Aggregation
    (read by ``engine/sa/risk_weights.py``'s CRR and Basel 3.1 dispatchers and
    its Art. 127 defaulted-RE limb, by ``engine/sa/b31_risk_weight_tables.py``'s
    real-estate route and Art. 124J weight, by the aggregator's applied-class
    overlay, and by ``reporting/corep/re_limbs.py`` — the OF 07.00 / OF 09.01
    real-estate limb rows)

Key responsibilities:
- ``is_commercial_re_class``: commercial real estate, by class string or by
  ``property_type``
- ``is_residential_re_class``: residential real estate, by class string
- ``is_residential_property``: the Art. 124J(2) / 124J(3) residential test on an
  other real estate exposure, by ``property_type``

Why a module of its own: every reader must route on the SAME expression, or the
applied risk weight, the reported class and the Basel 3.1 loan-split carriers
can disagree about which real-estate branch priced a row. The Basel 3.1 table
module is one of those readers and ``risk_weights.py`` imports it, so the
predicates cannot live in ``risk_weights.py`` without an import cycle.

References:
- CRR Art. 124-126: exposures secured by mortgages on immovable property
- PS1/26 Art. 124-124L: real estate exposures (Basel 3.1)
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

logger = logging.getLogger(__name__)


def is_commercial_re_class(uc: pl.Expr) -> pl.Expr:
    """Match commercial real-estate exposures by class string or property_type.

    Used by the SA RE dispatchers and the Art. 127(3) defaulted-RESI rule
    to route ahead of the residential branch — ``COMMERCIAL_MORTGAGE``
    contains the ``MORTGAGE`` substring, so the residential dispatch
    would otherwise grab it.

    The ``property_type == "commercial"`` limb is why an exposure can take the
    Art. 126 / Art. 124H-124I commercial risk weight while its routing
    ``exposure_class`` still says ``corporate``. The aggregator's applied-class
    overlay (``_add_exposure_class_applied``) reuses this exact predicate to put
    such an exposure in Art. 112(1)(i) for reporting: sharing one expression is
    what keeps the reported class and the applied risk weight from drifting apart.

    The exact equality is safe for any spelling the input contract accepts,
    because the hierarchy hands ``property_type`` over lowercased
    (``hierarchy/enrich.add_collateral_ltv``); the contract accepts any case, and
    before P1.362 a ``"Commercial"`` spelling missed this limb and a
    retail-mortgage row fell to the residential branch.
    """
    return (
        uc.str.contains("COMMERCIAL", literal=True)
        | uc.str.contains("CRE", literal=True)
        | (pl.col("property_type").fill_null("") == "commercial")
    )


def is_residential_re_class(uc: pl.Expr) -> pl.Expr:
    """Match residential RE — relies on commercial being routed first."""
    return uc.str.contains("MORTGAGE", literal=True) | uc.str.contains("RESIDENTIAL", literal=True)


@cites("PS1/26, paragraph 124J")
def is_residential_property() -> pl.Expr:
    """Whether an other real estate exposure takes Art. 124J(2) (residential) rather
    than Art. 124J(3) (commercial): its ``property_type`` is residential.

    Read by the Art. 124J weight (``b31_other_re_rw_expr``) and by the OF 07.00 rows
    0351-0354 that report it (``reporting/corep/re_limbs.py``), so a row names the
    paragraph whose weight the leg took. A null ``property_type`` reads as
    commercial, the paragraph with the 60% floor.
    """
    return pl.col("property_type").fill_null("").str.to_lowercase() == "residential"
