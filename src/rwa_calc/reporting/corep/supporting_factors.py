"""
CRR supporting-factor attribution for the COREP "(-)" adjustment columns.

Pipeline position:
    OutputAggregator -> COREPGenerator -> {C 07.00, C 08.01/02, C 09.01/02}

Key responsibilities:
- Derive the null-safe infrastructure discriminator the SME adjustment column
  excludes on, so the two "(-)" columns describe DISJOINT populations
- Resolve the presence-tolerant equals terms that select one factor's applied
  rows, shared by all four adjustment-column call sites

Why one module rather than a copy per template. The same three-limb resolution
was written out separately in ``c07.py``, ``c08.py`` and ``c09.py``; the SME
limb double-counted an SME-and-infrastructure row into BOTH columns on all
three, and a fix applied to fewer than all four call sites would have left the
double-count live on the templates it missed.

References:
- CRR Art. 501 (SME supporting factor), Art. 501a (infrastructure)
- COREP Annex II: C 07.00 cols 0215/0216/0217/0220, C 08.01/02 cols
  0255/0256/0257/0260, C 09.01 cols 0080/0081/0082/0090, C 09.02 cols
  0110/0121/0122/0125 — each block reads "pre supporting factors",
  "(-) Deduction of the difference" x2, then "after supporting factors"
- EBA validation rule ``v09747_m`` (C 07.00.c, live, WARNING):
  ``{c0215} + {c0216} + {c0217} = {c0220}``
"""

from __future__ import annotations

import polars as pl

#: The null-safe "this row is flagged infrastructure" discriminator derived by
#: :func:`sf_infra_flag_exprs`. A template-owned derived column, read through
#: ``RowPredicate.equals``' presence-TOLERANT channel like ``c07_rated`` and the
#: two-basis flags — never the sealed ``is_infrastructure`` itself, which is
#: genuinely NULLABLE (``engine/classify/attributes.py`` derives it as a
#: substring match on ``product_type``, so it is null wherever that is null).
SF_INFRA_FLAG = "reporting_sf_infra"


def sf_infra_flag_exprs(cols: set[str]) -> list[pl.Expr]:
    """The :data:`SF_INFRA_FLAG` derivation, or ``[]`` on a frame without the
    sealed flag (a synthetic unit frame — the SME column then simply keeps its
    pre-disjointness population, rather than compiling to match-nothing).

    ``eq_missing`` and not ``== True`` / ``~``: a null ``is_infrastructure`` has
    to yield ``False`` here, because the SME column excludes on ``(flag, False)``
    and a null would otherwise drop a legitimate SME row out of col 0216
    entirely — a null-propagating ``!=`` moves the double-count into an
    under-count rather than removing it. ``~`` additionally raises on an
    all-null column.
    """
    if "is_infrastructure" not in cols:
        return []
    return [pl.col("is_infrastructure").eq_missing(True).alias(SF_INFRA_FLAG)]


def sf_adjustment_terms(
    cols: set[str], dedicated: str, flag_col: str, *, exclude_infra: bool = False
) -> tuple[tuple[str, str | bool], ...] | None:
    """The presence-tolerant equals terms selecting the rows one factor was
    applied to, or ``None`` when the adjustment cannot be computed at all (no
    ``rwa_pre_factor`` snapshot, or no discriminator for this factor) and the
    caller must publish a structural null.

    Three limbs, in preference order:

    1. ``dedicated`` — the factor's own applied flag (note the retired
       asymmetric names: ``sme_supporting_factor_applied`` vs
       ``infrastructure_factor_applied``). **Unreachable in production, kept
       deliberately.** The engine emits ONE generic ``supporting_factor_applied``
       (``engine/supporting_factors.py::apply_factors``); the dedicated pair
       lives only in ``data/schemas.py``'s aspirational
       ``CRR_OUTPUT_SCHEMA_ADDITIONS`` and on the legacy INPUT side, where
       ``analysis/legacy_ledger.py`` enumerates it as an alternative source a
       customer mapping may supply. It is the producer's own attribution and so
       is taken verbatim, ``exclude_infra`` included: a frame that names the
       factor is not second-guessed.
    2. The generic fallback — ``flag_col`` (``is_sme`` / ``is_infrastructure``)
       conjoined with ``supporting_factor_applied``. **This is the only limb a
       real run takes**, and the one the disjointness below is about.
    3. Neither available -> ``None``.

    ``exclude_infra`` (set by the SME column only) is what makes the two columns
    disjoint. ``supporting_factor = min(sme_factor, infra_factor)``
    (``engine/supporting_factors.py``), and the CRR pack pins
    ``infrastructure_factor = 0.75`` strictly below the SME blend's floor
    ``sme_factor_under_threshold = 0.7619`` — the blend is a convex combination
    of that and ``sme_factor_above_threshold = 0.85``, so it lies in
    [0.7619, 0.85] whenever the SME factor applies at all. So on a row eligible
    for both, the infrastructure factor ALWAYS wins the minimum: the whole
    relief is attributable to Art. 501a and col 0216 must report nothing.
    ``tests/acceptance/crr/test_scenario_crr_f_supporting_factors.py`` pins both
    ends of that inequality (0.75 flat; ``0.7619 <= sf <= 1.0``), so a
    recalibration that inverted it would fail there rather than silently
    re-inverting the attribution here.
    """
    if "rwa_pre_factor" not in cols:
        return None
    if dedicated in cols:
        return ((dedicated, True),)
    if flag_col not in cols or "supporting_factor_applied" not in cols:
        return None
    terms: tuple[tuple[str, str | bool], ...] = (
        (flag_col, True),
        ("supporting_factor_applied", True),
    )
    # DO NOT gate this on ``SF_INFRA_FLAG in cols``. It must be the SOURCE
    # column, exactly as ``sf_infra_flag_exprs`` gates on, or the derivation and
    # the term silently disagree — ``cols`` is the PRE-derivation column set in
    # c07.py/c08.py and the POST-derivation one in c09.py. Measured: gating on
    # the derived name fixed C 09.01 and left C 07.00, C 08.01/02 and C 09.02
    # double-counting, with every static gate and the whole unit suite green;
    # only a full pipeline run through all five templates showed it. And the
    # failure is not "no narrowing" — a term naming a column the frame lacks
    # compiles to ``pl.lit(False)`` (``RowPredicate._compile``), so the wrong
    # gate would EMPTY col 0216 rather than widen it.
    if exclude_infra and "is_infrastructure" in cols:
        terms = (*terms, (SF_INFRA_FLAG, False))
    return terms
