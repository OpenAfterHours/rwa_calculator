"""
COREP post-execute passes shared by C 07.00, C 08.01/02 and C 09.01/02.

Pipeline position:
    cellspec.execute() -> these passes, on the REPORTED frame -> the bundle
    (the drill-down reads a cell's value from the reported frame, so it honours
    every pass here)

Key responsibilities:
- Render inert rows and rows with EMPTY subsets all-null (``null_empty_rows``).
- Emit the Annex II §1.3 "(-)"-labelled deduction columns as negative figures
  (``negate_deduction_cols``).
- Swap a provisions cell to the best available carrier when its base sum nets
  to ~0 (``provisions_postfix``, C 08.01/02/03/06).
- Fill the two C 08.01/02 columns the executor cannot bind — the off-balance-
  sheet slice of the col 0090 waterfall (``c08_off_bs_pre_ccf``) and the
  after-all-CRM total (``c08_after_all_crm``).

WHY HERE AND NOT IN ``reporting/kernel``: ``null_empty_rows`` reads
``RowPredicate`` / ``matched_counts`` from ``reporting/cellspec.py``, which
itself imports ``reporting/kernel`` — putting it under the kernel would invert
that layering. ``corep/`` is where every caller already lives, alongside the
other cross-template helper (``corep/crm_substitution.py``).

Each template module previously carried its own copy of both. They had already
converged term-for-term (each docstring said so), so the copies are folded into
one implementation per pass with the per-template scope passed in — the
``negative_cols`` set and the ``keep`` exemptions stay template-owned, because
those ARE the per-template decisions.

References:
- Reg (EU) 2021/451 Annex II §1.3 (the "(-)" sign convention)
- PRA PS1/26 Annex II §1.3 (the same convention on the OF templates)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from rwa_calc.reporting.cellspec import matched_counts, subset_rows
from rwa_calc.reporting.corep.crm_substitution import IRB_BLOCK_COL
from rwa_calc.reporting.kernel import safe_sum

if TYPE_CHECKING:
    from collections.abc import Mapping

    from rwa_calc.reporting.cellspec import RowPredicate

_LABEL_COLS: tuple[str, str] = ("row_ref", "row_name")


def null_empty_rows(
    frame: pl.DataFrame,
    class_df: pl.DataFrame,
    row_preds: Mapping[str, RowPredicate | None],
    keep: frozenset[str] = frozenset(),
) -> pl.DataFrame:
    """Render inert rows and rows with EMPTY subsets all-null.

    The retired per-template ``_null_row`` contract: the COREP zero policy
    applies only to POPULATED rows' unbound cells. A ``None`` predicate is an
    inert row; a constrained predicate matching nothing is an empty one; a
    constraint-free predicate (the Total row, no ``equals`` / ``any_of``) is
    never nulled.

    ``keep`` exempts rows whose content is a cross-sheet INFLOW: their own
    subset is legitimately empty (the money lives in other sheets), so nulling
    them would delete the component the published row sums need — visibly so on
    an inflow-only sheet, where EVERY constrained subset is empty.

    ON A TWO-BASIS TEMPLATE THE COUNT IS OVER THE UNION OF BOTH BASES, and that
    falls out rather than being coded: ``class_df`` is the sheet frame (the legs
    on this sheet under EITHER basis — ``kernel/bases.py::sheet_frame``) and the
    predicates passed here are the BASIS-FREE row terms, so a row is nulled only
    when it is empty on the origin basis AND on the post basis. Keying it on one
    basis would null out the very cells the split exists to publish — an
    inflow-only sheet's rows have no origin-basis leg at all, yet must report the
    exposure value and RWEA that arrived on them. The converse costs a
    fully-outflowed row a null it used to get: it reports real zeros in its
    exposure-value / RWEA columns against its real gross, which is what the
    ``{exposure value} <= {gross}`` family of published rules asks of it.
    """
    constrained = {
        ref: pred
        for ref, pred in row_preds.items()
        if pred is not None and (pred.equals or pred.any_of)
    }
    counts = matched_counts(class_df, constrained)
    null_refs = [
        ref
        for ref, pred in row_preds.items()
        if ref not in keep and (pred is None or ((pred.equals or pred.any_of) and counts[ref] == 0))
    ]
    if not null_refs:
        return frame
    value_cols = [col for col in frame.columns if col not in _LABEL_COLS]
    return frame.with_columns(
        pl.when(pl.col("row_ref").is_in(null_refs))
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(pl.col(col))
        .alias(col)
        for col in value_cols
    )


def negate_deduction_cols(frame: pl.DataFrame, negative_cols: frozenset[str]) -> pl.DataFrame:
    """Annex II §1.3: emit the "(-)"-labelled deduction columns as negatives.

    Runs AFTER the template's waterfalls have consumed the positive magnitudes.
    Intersecting with the frame's columns makes the framework-specific members
    (B31's C 08.01 cols 0035/0102/0103, CRR's 0256/0257) absent-column no-ops in
    the regime that lacks them.

    A zero deduction is normalised to ``+0.0``: plain ``-pl.col(col)`` flips the
    IEEE sign bit, so a ``0.0`` cell would serialise as ``-0.0`` (``+ 0.0`` does
    NOT clear it in Polars). Null stays null — ``== 0.0`` is null on a null row,
    so the ``otherwise`` branch returns ``-null``.
    """
    targets = [col for col in frame.columns if col in negative_cols]
    if not targets:
        return frame
    return frame.with_columns(
        pl.when(pl.col(col) == 0.0).then(pl.lit(0.0)).otherwise(-pl.col(col)).alias(col)
        for col in targets
    )


def c08_off_bs_pre_ccf(
    frame: pl.DataFrame,
    class_df: pl.DataFrame,
    row_preds: Mapping[str, RowPredicate | None],
) -> pl.DataFrame:
    """Fill C 08.01/02 col 0100 with the off-BS slice of the 0090 waterfall.

    Col 0100 ("of which: off balance sheet") sits in the POST-CRM PRE-CCF
    column group (the 0090 "Exposure after CRM substitution pre CCFs"
    waterfall), so it reports the off-BS share of that PRE-conversion-factor
    quantity — NOT the post-CCF exposure value (that is col 0120). The
    executor has no intra-row sub-waterfall verb, so 0100 is derived here per
    row over the row's ``c08_bs == "off"`` legs, mirroring ``_value_cells`` +
    ``crm_substitution.crm_waterfall`` term-for-term:

        0100 = off-BS gross (0020: the sealed reporting_gross_off_bs carrier)
             - off-BS substitution outflow (0070: the ``c08_prot_block``
               subtotal cols 0040/0050/0060 break down)

    It carries the waterfall's OWN correction: reading the breakdown columns AND
    the outflow subtotal — as this did before — deducts the same covered part
    twice, exactly as ``crm_waterfall`` did. Binding the same per-leg subtotal
    col 0070 binds keeps the memo a true slice of 0090 by construction rather
    than by two derivations agreeing.

    THE B31 COL 0035 TERM IS DELIBERATELY ABSENT, and that is load-bearing rather
    than an oversight: col 0035 is the Art. 166(3) on-balance-sheet netting of
    loans and deposits, so it has no off-balance-sheet share to slice. The BoE
    scoping says the same thing structurally — ``boe_b0746_1`` drops the 0035 term
    from the col 0090 waterfall on exactly the off-balance-sheet row family
    (``crm_substitution.C08_01_NETTING_EXEMPT_ROWS``), so an off-BS memo that
    subtracted it would contradict the published rule for row 0030 while claiming
    to be its slice. Do not "restore" it for symmetry with the on-BS rows.

    It is computed on POSITIVE magnitudes read from the raw ``class_df`` (so
    the result is independent of the later ``_negate`` sign pass). The 0080
    substitution INFLOW is EXCLUDED: it is a total-row cross-sheet scalar
    (``ReportingContext.substitution_inflow``, a per-destination-class
    aggregate with no leg-level on/off-BS attribution), so an off-BS memo
    cannot claim a share of it — recorded decision, matching 0090's own
    convention that the inflow only lands on the (constraint-free) total row.

    Every leg is either on- or off-BS (``c08_bs``) and the outflow carrier is a
    leg-level amount pro-rated across the two-leg guarantee split, so summing it
    over the off-BS legs is the EXACT slice. Inert (None-predicate) rows are left
    as the null placeholder for ``_null_empty_rows``; C 08.02 has none.
    """
    if "0100" not in frame.columns:
        return frame
    cols = set(class_df.columns)
    if "c08_bs" not in cols:
        return frame
    active = {ref: pred for ref, pred in row_preds.items() if pred is not None}
    if not active:
        return frame
    fixes: dict[str, float] = {}
    for row_ref, subset in subset_rows(class_df, active).items():
        off = subset.filter(pl.col("c08_bs") == "off")
        off_cols = set(off.columns)
        gross = safe_sum(off, off_cols, "reporting_gross_off_bs")
        fixes[row_ref] = gross - safe_sum(off, off_cols, IRB_BLOCK_COL)
    expr: pl.Expr = pl.col("0100")
    for row_ref, value in fixes.items():
        expr = (
            pl.when(pl.col("row_ref") == row_ref)
            .then(pl.lit(value, dtype=pl.Float64))
            .otherwise(expr)
        )
    return frame.with_columns(expr.alias("0100"))


def c08_after_all_crm(frame: pl.DataFrame) -> pl.DataFrame:
    """Fill C 08.01/02 col 0104 — exposure after ALL CRM, pre-conversion factors.

    PS1/26 Annex II (OF 08.01 col 0104): "Institutions shall report the value
    reported in column 0090 after adjusting for the reduction in exposure due to
    the Financial Collateral Comprehensive Method reported in columns 0101-0103."
    The published identity (boe_b1040) states it additively over the REPORTED
    (signed) cells::

        0104 = 0090 + 0101 + 0102

    — col 0103 is an "of which" sub-item of 0102 and is excluded, and 0102 is a
    "(-)"-labelled deduction, so on the POSITIVE magnitudes this pass sees (it
    runs before ``_negate``) the arithmetic is ``0090 + 0101 - 0102``.

    Cols 0101-0103 apply to slotting exposures only ("An institution shall only
    report values for exposures subject to the slotting approach") and are
    structural nulls today — no FCCM-under-slotting carrier is sealed — so 0104
    currently reproduces 0090 on every row. The subtraction is written out
    anyway so the cell stays truthful the day a carrier is wired.

    This is a post-execute pass and not a ``Formula`` cell because 0090, 0101 and
    0102 are themselves ``Formula`` cells and the executor refuses a formula that
    references another formula. A null 0090 (an inert row) keeps 0104 null for
    ``_null_empty_rows``; a frame without col 0104 (CRR, which has no FCCM
    column block) is left untouched.
    """
    if "0104" not in frame.columns or "0090" not in frame.columns:
        return frame
    total = pl.col("0090").fill_null(0.0)
    if "0101" in frame.columns:
        total = total + pl.col("0101").fill_null(0.0)
    if "0102" in frame.columns:
        total = total - pl.col("0102").fill_null(0.0)
    return frame.with_columns(
        pl.when(pl.col("0090").is_null())
        .then(pl.lit(None, dtype=pl.Float64))
        .otherwise(total)
        .alias("0104")
    )


def provisions_postfix(
    frame: pl.DataFrame,
    class_df: pl.DataFrame,
    row_preds: Mapping[str, RowPredicate | None],
    cols: set[str],
    *,
    ref: str,
) -> pl.DataFrame:
    """The provisions ladder: when the SCRA/GCRA base sum nets to ~0, swap the
    whole cell to the best available provisions carrier for the row subset (a
    value-dependent, PER-CELL branch — the recorded C 08 granularity, distinct
    from C 07.00's per-row ladder).

    The fallback carrier is ``provision_held`` when the frame carries it (the
    synthetic COREP unit frames supply it), else the sealed ``provision_allocated``
    (R10b). The retired ``provision_held``-only fallback was DEAD on every real
    submission: ``provision_held`` is an input pass-through the aggregator seal
    strips, so ``"provision_held" not in cols`` returned early and the provisions
    cells (C 08.01/02 col 0290, C 08.03 col 0110, C 08.06 col 0100) rendered a
    hard 0.0. ``provision_allocated`` is the sealed provisions carrier that IS
    meaningful on the IRB book: unlike C 07.00's ``provision_deducted`` (R9), the
    Art. 111(2) drawn-first deduction is SA-only (engine/crm/provisions.py —
    IRB/Slotting: provision_on_drawn = 0, provision_on_nominal = 0, so
    provision_deducted is STRUCTURALLY 0.0 on every IRB/slotting leg), whereas
    provision_allocated is tracked for all approaches (it feeds the IRB EL
    shortfall/excess). scra/gcra stay the preferred base; a book that supplies
    them non-degenerately keeps that granular figure."""
    fallback_col = (
        "provision_held"
        if "provision_held" in cols
        else "provision_allocated"
        if "provision_allocated" in cols
        else None
    )
    if ref not in frame.columns or fallback_col is None:
        return frame
    needed: dict[str, RowPredicate | None] = {}
    for row_ref, pred in row_preds.items():
        if pred is None:
            continue
        current = frame.filter(pl.col("row_ref") == row_ref)
        if current.height == 0 or current[ref][0] is None:
            continue
        if abs(current[ref][0]) >= 1e-9:
            continue
        needed[row_ref] = pred
    fixes: dict[str, float] = {}
    for row_ref, subset in subset_rows(class_df, needed).items():
        if subset.height == 0:
            continue
        fixes[row_ref] = float(subset[fallback_col].fill_null(0.0).sum())
    if not fixes:
        return frame
    expr: pl.Expr = pl.col(ref)
    for row_ref, value in fixes.items():
        expr = pl.when(pl.col("row_ref") == row_ref).then(pl.lit(value)).otherwise(expr)
    return frame.with_columns(expr.alias(ref))


def c08_06_zero_row(column_refs: tuple[str, ...], rw_display: str) -> dict[str, float | None]:
    """C 08.06: the zero-fill for an empty non-Total row: every cell 0.0
    except 0070 = the row definition's display risk weight ("50%" -> 0.5;
    unparseable/blank -> None)."""
    values: dict[str, float | None] = dict.fromkeys(column_refs, 0.0)
    if rw_display:
        try:
            values["0070"] = float(rw_display.replace("%", "").strip()) / 100.0
        except ValueError:
            values["0070"] = None
    else:
        values["0070"] = None
    return values


def c08_06_apply_overrides(
    frame: pl.DataFrame, overrides: dict[str, dict[str, float | None]]
) -> pl.DataFrame:
    if not overrides:
        return frame
    exprs: list[pl.Expr] = []
    value_cols = [col for col in frame.columns if col not in ("row_ref", "row_name")]
    for col in value_cols:
        expr = pl.col(col)
        touched = False
        for row_ref, values in overrides.items():
            if col in values:
                expr = (
                    pl.when(pl.col("row_ref") == row_ref)
                    .then(pl.lit(values[col], dtype=pl.Float64))
                    .otherwise(expr)
                )
                touched = True
        if touched:
            exprs.append(expr.alias(col))
    return frame.with_columns(exprs) if exprs else frame
