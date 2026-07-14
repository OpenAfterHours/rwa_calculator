"""
Pillar 3 CMS1 — Modelled vs standardised RWEA comparison by risk type,
declarative (Basel 3.1 only).

Pipeline position:
    sealed aggregator-exit ledger -> build_cms1_spec() -> cellspec.execute()
        -> CMS1 DataFrame

Cell semantics (recorded decisions, this slice):

- Basel 3.1 only ("shall be completed only by firms that use the internal
  model approaches set out in Article 92(3A)"); returns None under CRR.
- **The columns PARTITION the row** (Annex II): cell 0010/a covers "exposures
  where the RWA is NOT computed based on the standardised approach (ie subject
  to the credit risk IRB approaches (F-IRB, A-IRB and supervisory slotting))",
  cell 0010/b the "RWA which result from applying the ... standardised
  approach", and cell 0010/c is "the sum of cells 0010/a and 0010/b". Column b
  is therefore the COMPLEMENT of the modelled set, never an SA allow-list: an
  unrecognised approach label falls into b rather than into neither column
  (recorded fix 2026-07-14; before it, b was ``("standardised", "equity")`` —
  which omits ``standardised_ccr``, so every SA-CCR leg matched neither column
  and column c silently dropped the whole CCR charge: CMS1's Total reported
  2,500,000 against CMS2's 4,060,296.72 on the same book). Equity sits on the
  standardised side: "exposures calculated according to the SA for credit risk
  include equity exposures subject to the IRB Equity Transitional".
- Columns a/b sum ``rwa_final`` (post-output-floor — the floored figure; the
  pre/post-floor question is a separate recorded item). Column d sums
  ``sa_rwa`` — "RWA as would result from applying the ... standardised approach
  to ALL exposures giving rise to the RWA reported in cell 0010/c", i.e. the
  SA-equivalent of THAT ROW's population, not of the whole book. ``sa_rwa`` is
  the pre-supporting-factor SA-equivalent (the engine's floor convention; the
  post-factor variant and the floor's fallback-path divergence are recorded
  follow-ups).
- **Rows.** 0010 ("Credit risk", which "excludes ... capital requirements
  relating to a counterparty credit risk charge, which are reported in row
  0020") and 0020 (CCR) partition the credit-risk book by ``risk_type``; 0080
  (Total) is the whole book and hence their sum. Rows 0030-0070
  (CVA/securitisation/market/op-risk/residual) stay a FIXED all-null set —
  genuinely out of scope for a credit-risk calculator, and null is not the same
  claim as 0.0. Row 0020 is BOUND and zero-fills on a book with no CCR.

References:
- PRA PS1/26 Art. 456(1)(a), Art. 2a(1); Annex II (UKB CMS1 instructions)
- CRR Art. 153(5) (supervisory slotting — an IRB-chapter approach)
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8)
- docs/plans/c07-ccr-derivatives.md §4 D2 (the missing CCR row this fixes)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.reporting.cellspec import (
    CellSpec,
    Formula,
    RowPredicate,
    Sum,
    TemplateSpec,
    execute,
)
from rwa_calc.reporting.pillar3.templates import CMS1_COLUMNS, CMS1_ROWS

if TYPE_CHECKING:
    from collections.abc import Mapping

# Column a's population: exposures whose RWA is NOT computed under the
# standardised approach — "ie subject to the credit risk IRB approaches (F-IRB,
# A-IRB and supervisory slotting)". Supervisory slotting is Art. 153(5), an
# IRB-chapter approach. Column b is the COMPLEMENT of this set, never an
# allow-list (see the module docstring).
MODELLED_APPROACHES: tuple[str, ...] = ("foundation_irb", "advanced_irb", "slotting")

# Row 0020's population ("Counterparty credit risk"). Keyed by risk_type, never
# by the approach label: under CRR the CCR legs carry ``standardised`` and under
# Basel 3.1 ``standardised_ccr`` (the output-floor relabel), so an approach-based
# rule would no-op exactly where it matters. CCP default-fund contributions
# (Art. 307-309) are a Chapter 6 counterparty-credit-risk charge and carry
# ``rwa_final``, so they belong on row 0020 with the derivative and SFT legs.
_CCR_RISK_TYPES: tuple[str, ...] = ("CCR_DERIVATIVE", "CCR_SFT", "CCR_DEFAULT_FUND")

# The module-derived discriminator columns (the of02.py / c07 pattern):
# RowPredicate carries no negation and no risk-type field, so both the
# complement approach side and the risk-type side are derived here as their own
# Boolean flags and matched with tolerant ``equals``.
_IS_MODELLED: str = "cms1_is_modelled"
_IS_CCR: str = "cms1_is_ccr"

# 0010 (credit risk excl. CCR) + 0020 (CCR) partition the book; 0080 is the
# whole book, and therefore their sum.
_ROW_CCR_FLAG: dict[str, bool | None] = {"0010": False, "0020": True, "0080": None}


def _total_actual(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """Column c = a + b — the Annex II intra-row sum, over columns that
    PARTITION the row's population, so it is the row's whole actual RWA."""
    return (cells["a"] or 0.0) + (cells["b"] or 0.0)


@cites("PS1/26, paragraph 456")
def build_cms1_spec() -> TemplateSpec:
    """Build the CMS1 TemplateSpec (single Basel 3.1 layout).

    Carries the Art. 456(1)(a) citation for the by-risk-type modelled vs
    standardised RWEA comparison.
    """
    cells: dict[tuple[str, str], CellSpec] = {}
    for ref, is_ccr in _ROW_CCR_FLAG.items():
        # a MODELLED / b its COMPLEMENT: together the row's whole population,
        # so c (their Formula sum) is the row's whole actual RWA.
        cells[(ref, "a")] = CellSpec(
            Sum("rwa_final"),
            predicate=_predicate(is_ccr, modelled=True),
            empty_cell="zero",
        )
        cells[(ref, "b")] = CellSpec(
            Sum("rwa_final"),
            predicate=_predicate(is_ccr, modelled=False),
            empty_cell="zero",
        )
        cells[(ref, "c")] = CellSpec(Formula(refs=("a", "b"), fn=_total_actual))
        # d (full-SA) spans the row's whole population, modelled or not — the
        # SA recomputation of the exposures giving rise to column c. Zero-fills
        # on an empty population; ``sa_rwa`` absent still yields null.
        cells[(ref, "d")] = CellSpec(
            Sum("sa_rwa"),
            predicate=_predicate(is_ccr, modelled=None),
            empty_cell="zero",
        )
    return TemplateSpec(
        name="cms1",
        rows=tuple(CMS1_ROWS),
        column_refs=tuple(col.ref for col in CMS1_COLUMNS),
        cells=cells,
        empty_cell="null",
    )


def generate_cms1(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> pl.DataFrame | None:
    """Execute CMS1 over the full sealed ledger (Basel 3.1 only).

    Preserves the imperative generator's contracts: None under CRR; a
    missing RWA column records "CMS1: missing RWA column" and yields no
    template; column d is null when ``sa_rwa`` is absent (CRR-style frames
    or portfolios outside the output-floor scope).
    """
    if framework != "BASEL_3_1":
        return None
    if not ({"rwa_final", "rwa"} & cols):
        errors.append("CMS1: missing RWA column")
        return None
    return execute(_CMS1_SPEC, _prepare(results, cols))


def _prepare(results: pl.LazyFrame, cols: set[str]) -> pl.LazyFrame:
    """Derive the two discriminator columns the cell predicates key off.

    Both are ALWAYS derived — a missing source column yields a literal False,
    never an absent column. That matters: an absent column makes a tolerant
    ``equals`` term match NOTHING, which would drop the book out of BOTH
    column a and column b instead of routing it to the standardised side.
    """
    modelled = (
        pl.col("reporting_approach_origin").is_in(MODELLED_APPROACHES).fill_null(value=False)
        if "reporting_approach_origin" in cols
        else pl.lit(value=False)
    )
    is_ccr = (
        pl.col("risk_type").is_in(_CCR_RISK_TYPES).fill_null(value=False)
        if "risk_type" in cols
        else pl.lit(value=False)
    )
    return results.with_columns(modelled.alias(_IS_MODELLED), is_ccr.alias(_IS_CCR))


def _predicate(is_ccr: bool | None, *, modelled: bool | None) -> RowPredicate | None:
    """The conjunctive cell predicate: a risk-type side and an approach side.

    ``None`` on either axis imposes no constraint (row 0080 spans both risk-type
    sides; column d spans both approach sides).
    """
    terms: list[tuple[str, str | bool]] = []
    if is_ccr is not None:
        terms.append((_IS_CCR, is_ccr))
    if modelled is not None:
        terms.append((_IS_MODELLED, modelled))
    return RowPredicate(equals=tuple(terms)) if terms else None


# Built once (the layout is static). Defined last: the builder reads the
# ``_predicate`` helper below it, so the constant cannot be bound before it.
_CMS1_SPEC: TemplateSpec = build_cms1_spec()
