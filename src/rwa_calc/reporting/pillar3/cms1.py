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
  (Total) is the whole book and hence their sum. Rows 0030-0060
  (CVA/securitisation/market/op-risk) stay a FIXED all-null set — genuinely out
  of scope for a credit-risk calculator, and null is not the same claim as 0.0.
  Row 0020 is BOUND and zero-fills on a book with no CCR.
- **Row 0070 is bound, and it is deliberately INCOMPLETE.** Its instruction
  covers "RWA not captured within rows 0010 to 0060 (ie the RWA arising from
  equity investments in funds (rows 12 to 14 in Template OV1), settlement risk
  …)", and this calculator can produce exactly ONE of those components: the
  Art. 112(1)(o) CIU RWEA (P2.54). Settlement risk, the trading-book switch and
  threshold deductions are genuinely outside it and are NOT represented, so a
  populated row 0070 is a CIU figure, never a complete residual — do not read it
  as one, and do not infer from a 0.0 here that the other components are zero.
  Binding it is what keeps 0080 = 0010 + 0020 + 0070 true once the CIU leaves
  row 0010, and what makes the published ``CMS2 r0070 == CMS1 r0010`` hold.
  Unlike every other bound row it does NOT zero-fill: a CIU-free book leaves all
  four cells null, because 0.0 there would assert the components it cannot see
  are nil. The cost of that choice is visible on a book WITH a CIU — column a
  (modelled) reads null rather than 0.0, since the null/zero policy is one
  decision per cell and the row-empty case is the one worth getting right.

Lineage-instrumented (R21): ``cms1_plans`` exposes the single (no sheet axis)
execution plan — its frame is the full sealed ledger with the derived
``cms1_is_modelled`` / ``cms1_is_ccr`` discriminators — so ``reporting.lineage``
can drill into a reported cell. CMS1 is Basel 3.1 only, so ``cms1_plans`` (like
``generate_cms1``) yields NOTHING under CRR: lineage then degrades to a clean
"no lineage" 404, never a crash.

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
from rwa_calc.reporting.metadata import ReportingContext
from rwa_calc.reporting.pillar3.templates import CMS1_COLUMNS, CMS1_ROWS, CMS2_TOTAL_CLASSES
from rwa_calc.reporting.plans import SheetPlan

if TYPE_CHECKING:
    from collections.abc import Mapping

# Single-frame lineage key: CMS1 has no sheet axis, so its one plan keys under a
# canonical name (see reporting.plans / _resolve_sheet_key single_frame path).
_SHEET_KEY = "cms1"

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

#: The credit-risk population discriminator, SHARED with CMS2 (``derive_in_credit_risk``).
#: ONE sentence of PS1/26 governs both templates: row 0070's instruction reads "RWA
#: not captured within rows 0010 to 0060 (ie the RWA arising from equity investments
#: in funds (rows 12 to 14 in Template OV1), settlement risk …)", so an
#: Art. 112(1)(o) CIU's RWEA belongs in row 0070, is therefore NOT in rows 0010-0060,
#: and is therefore outside the credit-risk RWA that CMS2 decomposes.
IN_CREDIT_RISK: str = "cms_in_credit_risk"

# Row axes: (is_ccr, in_credit_risk). 0010 (credit risk excl. CCR and excl. the
# row-0070 carve-out) + 0020 (CCR) + 0070 (the carve-out) partition the book; 0080
# is the whole book, and therefore their sum. 0020 takes no credit-risk-population
# term: a CCR leg cannot be a CIU, so constraining it would only add a way for the
# CCR charge to fall out of every row.
_RESIDUAL_ROW: str = "0070"
_ROW_AXES: dict[str, tuple[bool | None, bool | None]] = {
    "0010": (False, True),
    "0020": (True, None),
    _RESIDUAL_ROW: (None, False),
    "0080": (None, None),
}


def _total_actual(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """Column c = a + b — the Annex II intra-row sum, over columns that
    PARTITION the row's population, so it is the row's whole actual RWA."""
    return (cells["a"] or 0.0) + (cells["b"] or 0.0)


def _total_actual_or_null(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """Row 0070's column c: the same sum, but NULL when neither side is populated.

    ``_total_actual`` would report 0.0 on an empty population, which on the
    incomplete residual row is a claim this calculator cannot make — see the
    module docstring.
    """
    if cells["a"] is None and cells["b"] is None:
        return None
    return (cells["a"] or 0.0) + (cells["b"] or 0.0)


@cites("PS1/26, paragraph 456")
def build_cms1_spec() -> TemplateSpec:
    """Build the CMS1 TemplateSpec (single Basel 3.1 layout).

    Carries the Art. 456(1)(a) citation for the by-risk-type modelled vs
    standardised RWEA comparison.
    """
    cells: dict[tuple[str, str], CellSpec] = {}
    for ref, (is_ccr, in_cr) in _ROW_AXES.items():
        # Row 0070 is the ONE row whose empty population must stay NULL rather
        # than zero-fill: it carries a single component of a residual whose other
        # components (settlement risk, the trading-book switch, threshold
        # deductions) this calculator cannot see, so 0.0 on a CIU-free book would
        # claim those are nil. Every other row is a claim the calculator can make.
        residual = ref == _RESIDUAL_ROW
        total_fn = _total_actual_or_null if residual else _total_actual
        # a MODELLED / b its COMPLEMENT: together the row's whole population,
        # so c (their Formula sum) is the row's whole actual RWA.
        cells[(ref, "a")] = CellSpec(
            Sum("rwa_final"),
            predicate=_predicate(is_ccr, modelled=True, in_credit_risk=in_cr),
            empty_cell="null" if residual else "zero",
        )
        cells[(ref, "b")] = CellSpec(
            Sum("rwa_final"),
            predicate=_predicate(is_ccr, modelled=False, in_credit_risk=in_cr),
            empty_cell="null" if residual else "zero",
        )
        cells[(ref, "c")] = CellSpec(Formula(refs=("a", "b"), fn=total_fn))
        # d (full-SA) spans the row's whole population, modelled or not — the
        # SA recomputation of the exposures giving rise to column c. Zero-fills
        # on an empty population; ``sa_rwa`` absent still yields null.
        cells[(ref, "d")] = CellSpec(
            Sum("sa_rwa"),
            predicate=_predicate(is_ccr, modelled=None, in_credit_risk=in_cr),
            empty_cell="null" if residual else "zero",
        )
    return TemplateSpec(
        name="cms1",
        rows=tuple(CMS1_ROWS),
        column_refs=tuple(col.ref for col in CMS1_COLUMNS),
        cells=cells,
        empty_cell="null",
    )


def cms1_plans(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, SheetPlan]:
    """Build the single CMS1 execution plan (the lineage seam).

    CMS1 has no sheet axis, so the one plan keys under the single-frame
    canonical key. The plan's frame is the full sealed ledger carrying the
    derived ``cms1_is_modelled`` / ``cms1_is_ccr`` discriminators the cell
    predicates key off. CMS1 is Basel 3.1 only, so a CRR run yields ``{}`` —
    lineage then returns a clean "no lineage" rather than crashing. Preserves
    the imperative generator's error contract: a missing RWA column records the
    CMS1 error and yields no plan. There is no post-execute pass, so
    ``negative_cols`` is empty.
    """
    if framework != "BASEL_3_1":
        return {}
    if not ({"rwa_final", "rwa"} & cols):
        errors.append("CMS1: missing RWA column")
        return {}
    return {
        _SHEET_KEY: SheetPlan(
            spec=_CMS1_SPEC,
            frame=_prepare(results, cols).collect(),
            ctx=ReportingContext(),
            negative_cols=frozenset(),
        )
    }


def generate_cms1(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """Execute CMS1 over the full sealed ledger (Basel 3.1 only; keyed like
    ``cms1_plans``).

    The thin consumer of ``cms1_plans``: it executes each plan under the same
    key, so a cell's reported value and its spec agree. Preserves the
    imperative generator's contracts: an empty dict under CRR (the dispatch
    router unwraps it to ``None``); a missing RWA column records the CMS1 error
    and yields no frame; column d is null when ``sa_rwa`` is absent (CRR-style
    frames or portfolios outside the output-floor scope). CMS1 has no
    post-execute pass, so this is a plain ``execute``.
    """
    return {
        key: execute(plan.spec, plan.frame, plan.ctx)
        for key, plan in cms1_plans(results, cols, framework, errors).items()
    }


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
    return derive_in_credit_risk(
        results.with_columns(modelled.alias(_IS_MODELLED), is_ccr.alias(_IS_CCR)), cols
    )


def derive_in_credit_risk(results: pl.LazyFrame, cols: set[str]) -> pl.LazyFrame:
    """Add :data:`IN_CREDIT_RISK` — the population rows 0010/0020 and the whole of
    CMS2 decompose. SHARED with CMS2, because one PS1/26 sentence governs both.

    ALWAYS derived, and literal True when ``exposure_class`` is absent: a tolerant
    ``equals`` term matches NOTHING on an absent column, so an absent class would
    empty row 0010 and CMS2's Total outright — the whole book reported nowhere.
    Every synthetic unit frame in the Pillar 3 estate is such a frame. A leg whose
    class the ledger did NOT seal is likewise inside the population: it cannot be a
    CIU, which is the only thing the carve-out removes.

    ``CMS2_TOTAL_CLASSES`` is the allow-list form of the same decision and is the
    single declaration of it — stated as a set so that a twentieth
    ``ExposureClass`` member is a decision rather than a silent admission.
    """
    in_credit_risk = (
        pl.col("exposure_class").is_in(list(CMS2_TOTAL_CLASSES)).fill_null(value=True)
        if "exposure_class" in cols
        else pl.lit(value=True)
    )
    return results.with_columns(in_credit_risk.alias(IN_CREDIT_RISK))


def _predicate(
    is_ccr: bool | None, *, modelled: bool | None, in_credit_risk: bool | None = None
) -> RowPredicate | None:
    """The conjunctive cell predicate: a risk-type side, an approach side and the
    credit-risk-population side.

    ``None`` on any axis imposes no constraint (row 0080 spans both risk-type
    sides and the whole population; column d spans both approach sides).
    """
    terms: list[tuple[str, str | bool]] = []
    if is_ccr is not None:
        terms.append((_IS_CCR, is_ccr))
    if modelled is not None:
        terms.append((_IS_MODELLED, modelled))
    if in_credit_risk is not None:
        terms.append((IN_CREDIT_RISK, in_credit_risk))
    return RowPredicate(equals=tuple(terms)) if terms else None


# Built once (the layout is static). Defined last: the builder reads the
# ``_predicate`` helper below it, so the constant cannot be bound before it.
_CMS1_SPEC: TemplateSpec = build_cms1_spec()
