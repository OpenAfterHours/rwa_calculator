"""
Real-estate class predicates shared by the SA risk-weight dispatchers.

Pipeline position:
    CRMProcessor -> SACalculator -> Aggregation
    (read by ``engine/sa/risk_weights.py``'s CRR and Basel 3.1 dispatchers and
    its Art. 127 defaulted-RE limb, by ``engine/sa/b31_risk_weight_tables.py``'s
    real-estate route, and by the aggregator's applied-class overlay)

Key responsibilities:
- ``is_commercial_re_class``: commercial real estate, by class string or by
  ``property_type``
- ``is_residential_re_class``: residential real estate, by class string

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
    """
    return (
        uc.str.contains("COMMERCIAL", literal=True)
        | uc.str.contains("CRE", literal=True)
        | (pl.col("property_type").fill_null("") == "commercial")
    )


def is_residential_re_class(uc: pl.Expr) -> pl.Expr:
    """Match residential RE — relies on commercial being routed first."""
    return uc.str.contains("MORTGAGE", literal=True) | uc.str.contains("RESIDENTIAL", literal=True)
