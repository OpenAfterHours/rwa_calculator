"""
COREP OF 02.01 — output floor comparison (Basel 3.1 only), declarative.

Pipeline position:
    sealed aggregator-exit ledger + OutputFloorConfig gate
        -> ONE TemplateSpec -> cellspec.execute() -> DataFrame | None

Cell semantics (recorded decisions, this slice):

- B31-only: CRR returns None (a None bundle field, no frame — the golden
  manifest records ``of_02_01: null`` and omits the frame).
- The entity gate stays OUTSIDE the executor: framework check, then
  ``OutputFloorConfig.is_floor_applicable()`` (a bare boolean — OF 02.01
  reads NOTHING else off the config and nothing off OutputFloorSummary).
  Nothing is read off ``OutputFloorSummary`` on purpose: its ``u_trea`` /
  ``s_trea`` are MODELLED-SUBSET quantities, not the Art. 92 aggregates
  (recorded engine defect, docs/plans/c07-ccr-derivatives.md §4 D6).
  Then the column-presence guard with the retired error string.
- **The columns PARTITION the book** (Annex II): column 0010 is
  "portfolios where RWAs are calculated using MODELLED approaches only",
  column 0020 "portfolios ... using STANDARDISED approaches only", and
  column 0030 is "a sum of 0010 and 0020, i.e. the complete current
  portfolio" — which only reconstitutes the portfolio BECAUSE they
  partition it. Column 0020 is therefore the COMPLEMENT of the modelled
  set, not an SA allow-list: an unrecognised approach label falls into
  0020 rather than into neither column (recorded fix 2026-07-14; before
  it, both columns summed the WHOLE ledger and 0030 reported
  U-TREA + S-TREA — 2.18x the book on the rich portfolio).
- Columns 0010/0020 sum ``rwa_pre_floor`` — the PRE-floor own-approach
  RWA (the mirror image of the estate-wide "rwa_final is already
  post-floor" trap: here the pre-floor carrier is deliberately the
  source). Column 0020 is the ACTUAL standardised-approach RWA, so it
  sums ``rwa_pre_floor``, not ``sa_rwa`` (the S-TREA leg in column 0040).
  Column 0040 (the S-TREA leg) sums ``sa_rwa`` over the row's whole
  population — that is what S-TREA is. Equity bypasses the SA calculator,
  so the aggregator populates equity's ``sa_rwa`` as its own pre-floor RWA
  (Basel 3.1 equity is SA-only, Art. 147A) — without which column 0040
  would silently drop equity's standardised-equivalent RWA (R4).
- **Rows.** 0010 ("Credit risk excluding CCR") and 0020 ("Counterparty
  credit risk") partition the credit-risk book by ``risk_type``; 0080
  (Total) is the whole book and hence their sum. Rows 0030-0070
  (CVA/securitisation/market/op-risk/other) stay a FIXED all-null set —
  genuinely out of scope for a credit-risk calculator, and null is not
  the same claim as 0.0.
- NO empty-frame early return: an empty portfolio still yields the 8-row
  frame with 0.0 on the populated rows.

References:
- PRA PS1/26 Art. 92 para 2A/3A (output floor scope); Annex II §1.3.2
- CRR Art. 153(5) (supervisory slotting — an IRB-chapter approach)
- docs/plans/phase7-declarative-reporting.md §3.2/§6 (S8)
- docs/plans/c07-ccr-derivatives.md §4 D3 (the double-count this fixes)
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
from rwa_calc.reporting.corep.templates import (
    OF_02_01_COLUMN_REFS,
    OF_02_01_ROW_SECTIONS,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_calc.contracts.config import OutputFloorConfig

# The fixed all-null risk-type rows (out of scope for a credit-risk-only
# calculator): CVA, securitisation, market risk, op risk, other. Row 0020
# (CCR) is BOUND — it zero-fills on a book with no CCR, which is a claim
# this calculator can actually make.
_NULL_ROWS: tuple[str, ...] = ("0030", "0040", "0050", "0060", "0070")

# 0010 (credit risk excl. CCR) + 0020 (CCR) partition the book; 0080 is the
# whole book, and therefore their sum.
_ROW_CCR_FLAG: dict[str, bool | None] = {"0010": False, "0020": True, "0080": None}

# Column 0010's population: "portfolios where RWAs are calculated using
# MODELLED approaches only". Supervisory slotting is Art. 153(5) — an
# IRB-chapter approach, reported in the CR IRB templates (C 08.06) — so it is
# modelled. Column 0020 is the COMPLEMENT of this set, never an allow-list.
#
# Deliberately LOCAL to OF 02.01 (the ``c02.py::_SA_APPROACHES`` precedent): a
# shared constant is how an approach-set decision leaks into CMS1/CMS2/OV1/
# CR4/CR5, which key their own recorded bases.
#
# NOT ``FLOOR_ELIGIBLE_APPROACHES`` (engine/aggregator/_schemas.py): that set
# answers a different question — which rows RECEIVE the floor add-on — and it
# CONTAINS ``standardised_ccr``, so reusing it would book an SA-CCR derivative
# as modelled RWA.
_MODELLED_APPROACHES: tuple[str, ...] = ("foundation_irb", "advanced_irb", "slotting")

# Row 0020's population ("Counterparty credit risk"). Keyed by risk_type, never
# by the approach label: under CRR the CCR legs carry ``standardised`` and under
# Basel 3.1 ``standardised_ccr`` (the output-floor relabel), so an approach-based
# rule would no-op exactly where it matters.
#
# The CCR set is THREE risk types, not two. ``CCR_DEFAULT_FUND`` (CCP
# default-fund contributions, Art. 307-309) is a Chapter 6 counterparty-credit-risk
# charge — same chapter as the SA-CCR derivative and FCCM SFT legs — so it belongs
# on row 0020, not on row 0010 ("Credit risk excluding CCR"). Do not trim it back
# to two: dropping it would book a default-fund contribution as NON-CCR here while
# CMS1 (whose set is the same three) books it as CCR, so one submission would carry
# two contradictory definitions of CCR. No fixture carries such a row today, so the
# third member is latent — that is not a reason to remove it.
#
# Deliberately LOCAL, like ``_MODELLED_APPROACHES`` above: each template owns its
# own tuple (recorded anti-pattern, docs/plans/c07-ccr-derivatives.md §4 D4 — a
# shared risk-type/approach constant is how one template's basis leaks into
# CR4/CR5/OV1, which key their own recorded bases).
_CCR_RISK_TYPES: tuple[str, ...] = ("CCR_DERIVATIVE", "CCR_SFT", "CCR_DEFAULT_FUND")

# The module-derived discriminator columns (the established pattern — c07_qccp,
# cr5_rw_bucket): RowPredicate carries no negation and no approach/risk-type
# field, so the complement side is derived here as its own Boolean flag.
_IS_MODELLED: str = "of02_is_modelled"
_IS_CCR: str = "of02_is_ccr"


def _u_trea(cells: Mapping[str, float | None], _prior: bool) -> float | None:
    """0030 (U-TREA) = 0010 + 0020 — the Annex II intra-row sum, over columns
    that PARTITION the row's population, so it is the complete portfolio."""
    return (cells["0010"] or 0.0) + (cells["0020"] or 0.0)


@cites("PS1/26, paragraph 1.3")
def generate_of_02_01(
    results: pl.LazyFrame,
    cols: set[str],
    framework: str,
    errors: list[str],
    *,
    output_floor_config: OutputFloorConfig | None = None,
) -> pl.DataFrame | None:
    """Execute OF 02.01 (modelled U-TREA vs standardised S-TREA)."""
    if framework != "BASEL_3_1":
        return None
    # Exempt entities do not report the output floor comparison
    # (Art. 92 para 2A restricts the floor to 3 entity-type/basis combos).
    if output_floor_config is not None and not output_floor_config.is_floor_applicable():
        return None
    if "rwa_pre_floor" not in cols or "sa_rwa" not in cols:
        errors.append(
            "OF 02.01 skipped: rwa_pre_floor and/or sa_rwa columns not found "
            "(output floor not applied)"
        )
        return None
    rows = tuple(row for section in OF_02_01_ROW_SECTIONS for row in section.rows)
    column_refs = tuple(OF_02_01_COLUMN_REFS)
    cells: dict[tuple[str, str], CellSpec] = {}
    for ref, is_ccr in _ROW_CCR_FLAG.items():
        # 0010 MODELLED / 0020 its COMPLEMENT: together the row's whole
        # population, so 0030 (their Formula sum) is the complete portfolio.
        cells[(ref, "0010")] = CellSpec(
            Sum("rwa_pre_floor"), predicate=_predicate(is_ccr, modelled=True)
        )
        cells[(ref, "0020")] = CellSpec(
            Sum("rwa_pre_floor"), predicate=_predicate(is_ccr, modelled=False)
        )
        cells[(ref, "0030")] = CellSpec(Formula(refs=("0010", "0020"), fn=_u_trea))
        # 0040 (S-TREA) spans the row's whole population, modelled or not.
        cells[(ref, "0040")] = CellSpec(Sum("sa_rwa"), predicate=_predicate(is_ccr, modelled=None))
    spec = TemplateSpec(
        name="of_02_01", rows=rows, column_refs=column_refs, cells=cells, empty_cell="zero"
    )
    frame = execute(spec, _prepare(results, cols))
    return _null_fixed_rows(frame, list(_NULL_ROWS))


def _prepare(results: pl.LazyFrame, cols: set[str]) -> pl.LazyFrame:
    """Derive the two discriminator columns the row/column predicates key off.

    Both are ALWAYS derived — a missing source column yields a literal False,
    never an absent column. That matters: an absent column makes a tolerant
    ``equals`` term match NOTHING, which would drop the book out of both
    columns 0010 and 0020 instead of routing it to the standardised side.
    """
    modelled = (
        pl.col("approach_applied").is_in(_MODELLED_APPROACHES).fill_null(value=False)
        if "approach_applied" in cols
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
    sides; column 0040 spans both approach sides).
    """
    terms: list[tuple[str, str | bool]] = []
    if is_ccr is not None:
        terms.append((_IS_CCR, is_ccr))
    if modelled is not None:
        terms.append((_IS_MODELLED, modelled))
    return RowPredicate(equals=tuple(terms)) if terms else None


def _null_fixed_rows(frame: pl.DataFrame, row_refs: list[str]) -> pl.DataFrame:
    """Render the FIXED out-of-scope row set all-null (exact null positions
    are golden-gated; the zero policy would otherwise render 0.0)."""
    if not row_refs:
        return frame
    value_cols = [col for col in frame.columns if col not in ("row_ref", "row_name")]
    return frame.with_columns(
        pl.when(pl.col("row_ref").is_in(row_refs))
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col(col))
        .alias(col)
        for col in value_cols
    )
