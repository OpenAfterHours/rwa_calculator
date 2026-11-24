"""
Subordinated-debt predicates shared by the SA risk-weight paths.

Pipeline position:
    CRMProcessor -> SACalculator -> Aggregation
    (read by ``engine/sa/risk_weights.py``'s Basel 3.1 override chain, by its
    Art. 127 defaulted override, and by the CRR Art. 139(2) seniority test in
    ``engine/sa/issuer_rating_seniority.py``)

Key responsibilities:
- ``is_subordinated``: the bare seniority test, the single home of the
  ``seniority`` null default.
- ``is_b31_subordinated_debt``: which rows take the PS1/26 Art. 133(5) 150%
  — subordinated institution, corporate and specialised-lending exposures.

Why a module of its own: the risk-weight chain and the defaulted override must
read the SAME predicate, or the Table A2 priority between row (3) subordinated
debt and row (5) default can differ by path; and ``risk_weights.py`` sits at the
``max_engine_module_loc`` ratchet, so the predicate's scope note cannot grow
there.

References:
- PRA PS1/26 Art. 133(5): 150% for a subordinated debt instrument, own funds
  instrument or equity instrument not classified as an equity exposure
- PRA PS1/26 Art. 112(2) Table A2 row (3): ranks above the corporate class
- PRA PS1/26 Art. 122A: specialised lending is a corporate sub-class
"""

from __future__ import annotations

import logging

import polars as pl
from watchfire import cites

logger = logging.getLogger(__name__)


@cites("PS1/26, paragraph 133")
def is_b31_subordinated_debt(upper_class: pl.Expr) -> pl.Expr:
    """B31 subordinated-debt predicate — Art. 112 Table A2 priority 3.

    Shared by the risk-weight chain and the defaulted override so the two
    cannot drift; the seniority half is ``is_subordinated``, so the single
    ``seniority.fill_null`` site is not duplicated (check-11 ratchets
    ``engine_fill_null_sites``).

    Scoped to institution / corporate deliberately: the Art. 133 150% is not a
    universal subordinated weight, and widening it would re-price subordinated
    sovereign and retail rows that today correctly take their class weight.
    The quasi-sovereign classes (PSE / RGLA / MDB / CGCB) stay out pending an
    owner decision (review IV-03).

    Specialised lending is IN scope: PS1/26 Art. 122A makes it a corporate
    sub-class, and Art. 133(5) — "An institution shall assign a risk weight of
    150% to an exposure that is a subordinated debt instrument ... and is not
    classified as an equity exposure" — sits in Table A2 row (3), above the
    corporate class. An SL row keeps ``exposure_class = specialised_lending``
    for approach routing, which the INSTITUTION / CORPORATE match never caught,
    so a mezzanine project-finance loan took its 100% / 130% / 80% Art. 122B
    type weight instead (review IV-03). CRR is untouched: this predicate is
    read only on the Basel 3.1 paths.

    Args:
        upper_class: ``exposure_class`` upper-cased by the caller.

    Returns:
        Boolean expression, True where the Art. 133(5) 150% applies.
    """
    return is_subordinated() & (
        upper_class.str.contains("INSTITUTION", literal=True)
        | upper_class.str.contains("CORPORATE", literal=True)
        | upper_class.str.contains("SPECIALISED", literal=True)
    )


def is_subordinated() -> pl.Expr:
    """True where the exposure ranks junior (``seniority == "subordinated"``).

    The class-free half of the subordinated-debt predicates, so the CRR
    Art. 139(2) seniority test can read seniority without importing
    ``is_b31_subordinated_debt``'s class limbs. A null ``seniority`` is senior,
    matching the SA input contract default.
    """
    return pl.col("seniority").fill_null("senior") == "subordinated"
