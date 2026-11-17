"""
C 07.00 / OF 07.00 risk-weight rows — the band each basis reports a leg at.

Pipeline position:
    corep/c07.py::_prepare (again after the loan split, in c07_plans) -> rw_band_exprs()
        -> the c07_rw_band / c07_rw_band_origin discriminators
        -> the risk-weight row cells (``origin_band_terms`` in c07._row_cells) and the
           empty-row rule (``band_row_presence`` in c07_sheet_scope)

Key responsibilities:
- Band a leg on the weight the POST basis reports it at (cols 0160-0235, and the
  col 0100 inflow the substitution router lands on a row): ``rw_band_expr``.
- Band a leg on the weight the ORIGIN basis reports it at (cols 0010-0150): the
  obligor's own pre-substitution weight where Art. 235 substitution was applied
  (``kernel/bases.py::origin_risk_weight``).
- Say when a risk-weight row is non-empty on a sheet: a leg is on that sheet under
  a basis AND at that basis's band.

THE RISK-WEIGHT ROW IS PER BASIS. PS1/26 Annex II
(ps1-26-annex-ii-reporting-instructions.pdf), repeating the C 07.00 text:

- p.94, rows 0140-0280: "Institutions shall report the information on the
  allocation of risk weights within the respective exposure class".
- p.84, cols 0090 / 0100: "Outflows shall correspond to the covered part of the
  Original Exposure pre-conversion factors that is deducted from the obligor's
  exposure class and subsequently assigned to the protection provider's exposure
  class. That amount shall be considered as an inflow into the protection provider's
  exposure class." ... "Inflows and outflows within the same exposure classes shall
  also be reported."
- p.81, col 0010: the original exposure "without taking into account ... the effect
  of credit risk mitigation techniques".
- EBA Q&A 2014_1636 on the same C 07.00 text: "Decisive for the reporting of
  exposures in column 010 ... is not only the risk weight, but also the exposure
  class"; the guaranteed parts "are substituted to the exposure class of the
  protection provider ... included from column 100 and reported explicitly from
  column 150 onwards".

So cols 0010-0150 of a covered part sit in the OBLIGOR's own risk-weight row of the
obligor's sheet, and its col 0100 inflow and cols 0160-0235 in the PROVIDER's row of
the provider's sheet. One band served both until 2026-11: an unrated corporate loan
of 8,000,000, 2,800,000 of it covered by a CQS 2 institution, reported the
2,800,000 of original exposure in corporates row 0182 (30%) — a row Art. 122 gives
no corporate, which the Bank's ``boe_b0441`` / ``boe_b0441_1`` require empty — and
5,200,000 in row 0230 (100%). A SAME-class substitution puts one leg on one sheet
under both bases at two weights, which is why the bands are two columns rather than
one column per sheet.

How it composes with the other three things that choose a risk-weight row:

- The Article 133 weight of transitional equity is part of the POST weight, and a
  leg that was not substituted reports its post weight on the origin basis too. The
  carrier is written by the equity calculator alone, which runs no Art. 235
  substitution, so every leg carrying it bands on it on both bases.
- A substituted loan-split leg is split into its two parts on its own weight before
  the bands are taken (``kernel/rw_parts.py``), so its original exposure lands on
  the two part rows and its exposure value, whole, on the provider's row.
- Memorandum rows 0300 / 0320 carry a band term and read their own basis flags
  (``c07_sheet_scope.basis_flags``), so they band per basis like the rows they
  repeat: a covered default's original exposure at the obligor's Art. 127 weight.

References:
- PRA PS1/26 Annex II OF 07.00 col 0010 (p.81), cols 0090 / 0100 (p.84), rows
  0140-0280 (p.94); PS1/26 Art. 133, Art. 235
- EBA Q&A 2014_1636 (C 07.00 col 010 at the obligor class's own weight)
"""

from __future__ import annotations

import polars as pl
from watchfire import cites

from rwa_calc.reporting.cellspec import RowPredicate
from rwa_calc.reporting.corep.templates import get_sa_risk_weight_bands
from rwa_calc.reporting.kernel.bases import origin_risk_weight

#: The band label the POST basis reports a leg at (the risk-weight rows' own term).
RW_BAND_COL: str = "c07_rw_band"
#: The band label the ORIGIN basis reports a leg at.
RW_BAND_ORIGIN_COL: str = "c07_rw_band_origin"

# The catch-all a weight on no published rung lands in, so it is reported, never dropped.
_OTHER_RISK_WEIGHTS: str = "Other risk weights"
# The equity calculator's sealed carrier: the Article 133 weight rules 4.2 / 4.3 replaced.
_EQUITY_ART133_RW_COL: str = "risk_weight_pre_equity_transitional"
_RISK_WEIGHT: str = "risk_weight"

_Terms = tuple[tuple[str, str | bool], ...]


def rw_band_exprs(framework: str, cols: set[str]) -> list[pl.Expr]:
    """Both band columns, or none on a frame with no ``risk_weight`` to band."""
    if _RISK_WEIGHT not in cols:
        return []
    origin = origin_risk_weight(cols, _post_weight(cols))
    return [
        rw_band_expr(framework, cols).alias(RW_BAND_COL),
        _band(framework, origin).alias(RW_BAND_ORIGIN_COL),
    ]


@cites("PS1/26 Art. 133")
def rw_band_expr(framework: str, cols: set[str]) -> pl.Expr:
    """The POST-basis band label of one row — the label the inflow router lands on.

    One definition, used twice: ``rw_band_exprs`` derives ``c07_rw_band`` from it,
    and ``c07._sa_inflows`` hands the SAME expression to the substitution router, so
    a banded inflow lands on a row that exists. The ladder is regime-shaped
    (``get_sa_risk_weight_bands``; Basel 3.1 adds 15/25/30/40/45/60/65/80/85/105/
    110/130/135% sub-bands) and ends in the "Other risk weights" catch-all, so a
    weight matching no band is reported, never dropped.

    TRANSITIONAL EQUITY is banded on the Article 133 weight the transitional
    replaced, not the applied one. PS1/26 Annex II p.95: such exposures "shall be
    reported against the risk weights set out in Article 133 [...] disregarding the
    transitional provisions. However, the RWEA shall still reflect the transitional
    provisions"; p.96 names rows 0250 / 0261 for them. None of the rules 4.2 / 4.3
    weights (160-340%) is a rung, so banded on ``risk_weight`` the leg fell to "Other
    risk weights", which ``boe_b0458`` requires empty on sheet 0016. The carrier is
    coalesced INTO the ladder rather than mapped to a row name, so the catch-all
    still holds whatever it says; it is null off the transitional legs and absent on
    CRR and equity-free runs, where the ladder reads as before.
    """
    return _band(framework, _post_weight(cols))


def origin_band_terms(terms: _Terms) -> _Terms:
    """A row's terms with its band term keyed on the ORIGIN band instead."""
    return tuple(
        (RW_BAND_ORIGIN_COL, value) if column == RW_BAND_COL else (column, value)
        for column, value in terms
    )


def band_row_presence(terms: _Terms, origin_flag: str, post_flag: str) -> RowPredicate:
    """When a row is non-empty on a sheet, in step with the cells it publishes.

    A row keyed on a band is non-empty when a leg is on the sheet on the origin basis
    at its origin band, or on the post basis at its post band. Counted on the post
    band alone, the obligor's sheet kept the provider's row open on the strength of
    a leg none of its cells read, and published it as a row of zeros. Every other row
    is as before.
    """
    if not any(column == RW_BAND_COL for column, _value in terms):
        return RowPredicate(equals=terms)
    return RowPredicate(
        any_of=(
            RowPredicate(equals=((origin_flag, True), *origin_band_terms(terms))),
            RowPredicate(equals=((post_flag, True), *terms)),
        )
    )


def _post_weight(cols: set[str]) -> pl.Expr:
    """The weight the post basis reports a leg at: Art. 133's for transitional equity."""
    weight = pl.col(_RISK_WEIGHT).cast(pl.Float64, strict=False)
    if _EQUITY_ART133_RW_COL in cols:
        return pl.coalesce(pl.col(_EQUITY_ART133_RW_COL), weight)
    return weight


def _band(framework: str, weight: pl.Expr) -> pl.Expr:
    """The band label of ``weight`` on the regime's ladder, else the catch-all."""
    band_expr: pl.Expr = pl.lit(_OTHER_RISK_WEIGHTS)
    for rw_value, label in reversed(get_sa_risk_weight_bands(framework)):
        band_expr = (
            pl.when(weight.round(4) == round(rw_value, 4)).then(pl.lit(label)).otherwise(band_expr)
        )
    return band_expr
