"""
C / OF 08.01 — the row axis: which legs each row reads, and what arrives on it.

Pipeline position:
    corep/templates.py (the rows) + corep/ccf_buckets.py (the conversion-factor rows)
        -> here (each row's membership terms, each leg's conversion-factor row,
           the substitution inflow each row takes)
        -> corep/c08.py::c08_01_plans / generate_c08_01

Key responsibilities:
- The membership terms per row (``row_terms``) and the per-row predicates the
  generate post-passes rebuild from them (``row_preds``; row 0070's ``any_of``
  union is ``grades_pred``).
- Each leg's conversion-factor row on the Basel 3.1 layout (``ccf_row_exprs`` /
  ``ccf_row_expr``), and a WARNING when off-balance-sheet money falls in none
  (``warn_if_unbucketed``).
- Which substitution-inflow component each row's column 0080 takes
  (``INFLOW_KEYS``), the context that carries them (``inflow_context``), and the
  rows that report an inflow even with no legs of their own (``inflow_rows``).

These helpers lived in ``corep/c08.py``, which hosts seven templates and sits at
the reporting module line ceiling; the row axis is one coherent slice of it.

THE CONVERSION-FACTOR ROWS (Basel 3.1). Row 0030 "Off balance sheet items" is
broken down by conversion factor in rows 0031 (10%), 0032 (20%), 0001 (40%),
0033 (50%), 0034 (100%) and 0035 (own estimate). PS1/26 Annex II p.116: "For
exposures subject to the slotting approach, the FIRB approach, or the AIRB
approach where neither conversion factors nor EADs are estimated, institutions
shall report values in rows that correspond to the applicable conversion
factors in Article 111 ... For exposures subject to the AIRB approach for which
conversion factors are estimated, or where EADs are estimated directly,
institutions shall report values in row 0035." Each row is row 0030's own
membership narrowed to the legs ``corep/ccf_buckets.py`` assigns it
(``CCF_ROW``), on both bases exactly as row 0030 is, so every additive column of
row 0030 is the sum of the six (``boe_b0741`` / ``boe_b0742``). An empty bucket
is rendered empty, not zero, by the empty-row pass; the thirteen columns the
taxonomy does not publish on these rows are left out by
``corep/of08_published_cells.py``. The substitution inflow (column 0080) is split
the same way, by the bucket of the leg it came from.

References:
- PRA PS1/26 Annex II §3.3.3 (OF 08.01 rows 0010-0200; rows 0031-0035 and 0001,
  p.116); Reg (EU) 2021/451 Annex II §3.3 (C 08.01)
- Bank of England Banking Taxonomy v4.1.1 rules ``boe_b0741``, ``boe_b0742``,
  ``boe_b0746_1``; BoE v4.0.0 ``boe_b0744`` / ``boe_b0745``, EBA ``v0338_m``
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

import polars as pl

from rwa_calc.reporting.cellspec import RowPredicate
from rwa_calc.reporting.corep import c02_rows
from rwa_calc.reporting.corep.c08_sheets import BASIS
from rwa_calc.reporting.corep.ccf_buckets import (
    CCF_CARRIERS,
    OF08_01_CCF_ROWS,
    of08_01_ccf_row_expr,
)
from rwa_calc.reporting.corep.templates import get_irb_row_sections
from rwa_calc.reporting.metadata import SUBSTITUTION_INFLOW_CCF_PREFIX, ReportingContext

if TYPE_CHECKING:
    from rwa_calc.reporting.corep.crm_substitution import InflowBreakdown
    from rwa_calc.reporting.plans import RowTerms

logger = logging.getLogger(__name__)

#: The derived column holding each leg's conversion-factor row (Basel 3.1).
CCF_ROW: Final = "c08_ccf_row"

_BS_SIDE: Final = "c08_bs"
_OFF: Final = "off"
_OFF_BS_GROSS: Final = "reporting_gross_off_bs"

# Which ``ReportingContext`` inflow component each C 08.01 row's col 0080 takes.
# The Total row 0010 takes the whole inflow; rows 0020/0030 take its balance-sheet
# split. Both are needed: row 0010 is decomposed TWICE over the same columns — the
# balance-sheet axis (r0020+r0030+r0040+r0050+r0060, BoE ``boe_b0744``) and the IRB
# treatment axis (r0070+r0080+r0170+r0180, EBA ``v0338_m``, live ERROR; BoE
# ``boe_b0745``, both BoE rules withdrawn in v4.1.1) — and a Total-row-only inflow
# breached BOTH by exactly the inflow on cols 0080/0090/0104 (measured on the
# CRM-substitution portfolio). The balance-sheet split is unambiguous: the side is
# a property of the asset, not of substitution. Row 0030's own breakdown by
# conversion factor (``boe_b0742``) takes the off-balance-sheet part split by the
# bucket of the leg it came from (module docstring).
#
# ROWS 0070/0080 CARRY THE TREATMENT SPLIT, and binding them is only coherent
# BECAUSE C 08.02 now carries the inflow too. Four live ERROR rules —
# ``boe_b0752_8`` / ``boe_b0814_07`` (col 0080) and ``boe_b0752_9`` /
# ``boe_b0814_08`` (col 0090), two distinct identities each stated twice in the
# pack — require ``{OF08.01 r0070} = sum({OF08.02})`` on those columns. So the
# published set jointly demands that the inflow reach row 0070 AND that the
# C 08.02 grade rows sum to it: binding row 0070 alone would fix ``v0338_m`` (and
# v4.0.0's ``boe_b0745``) and break both identities. See ``c08._C08_02_INFLOW_ROW``.
INFLOW_KEYS: Final[dict[str, str]] = {
    "0010": "substitution_inflow",
    "0020": "substitution_inflow_on_bs",
    "0030": "substitution_inflow_off_bs",
    "0070": "substitution_inflow_graded",
    "0080": "substitution_inflow_slotting",
    **{ref: f"{SUBSTITUTION_INFLOW_CCF_PREFIX}{ref}" for ref in OF08_01_CCF_ROWS},
}


def row_terms(framework: str, cols: set[str]) -> dict[str, RowTerms | None]:
    """Membership terms per C 08.01 row ref (None = inert all-null row).

    Ports the retired section dispatch: section 1's "of which" rows are
    hardwired null; section 2 splits on/off-BS, and Basel 3.1's off-BS rows by
    conversion factor (module docstring) — its netting-set rows are inert;
    section 3 splits the origin approach (F-IRB/A-IRB vs slotting) plus the B31
    unrated-corporate memo rows. ``cols`` is accepted for the plan builders'
    shared signature.
    """
    terms: dict[str, RowTerms | None] = {}
    for section_index, section in enumerate(get_irb_row_sections(framework)):
        for row in section.rows:
            ref = row.ref
            if section_index == 0:
                terms[ref] = () if ref == "0010" else None
            elif section_index == 1:
                terms[ref] = _balance_sheet_terms(ref)
            elif ref == "0070":
                terms[ref] = None  # composed via any_of below
            elif ref == "0080":
                terms[ref] = (("reporting_approach_origin", "slotting"),)
            elif ref == "0190":
                terms[ref] = (("c08_unrated_corp", True),)
            elif ref == "0200":
                terms[ref] = (("c08_unrated_ig", True),)
            else:
                terms[ref] = None
    return terms


def grades_pred() -> RowPredicate:
    """Row 0070 (obligor grades/pools) — the F-IRB/A-IRB non-slotting union.

    A two-limb ``any_of`` over ``reporting_approach_origin`` (slotting reports on
    row 0080). Defined once and shared by ``c08._c08_01_spec`` (merges it into
    every 0070 cell) and ``row_preds`` (rebuilds it for the generate post-passes),
    so the drill-down's spec and the generator's predicate never drift."""
    return RowPredicate(
        any_of=(
            RowPredicate(equals=(("reporting_approach_origin", "foundation_irb"),)),
            RowPredicate(equals=(("reporting_approach_origin", "advanced_irb"),)),
        )
    )


def row_preds(terms: dict[str, RowTerms | None]) -> dict[str, RowPredicate | None]:
    """Rebuild the C 08.01 per-row predicates from the plan's row terms.

    The three generate post-passes need each row's ``RowPredicate`` — including row
    0070's ``any_of`` union, which simple equals-terms cannot express — so it is
    rebuilt from the same ``row_terms`` the plan carries (deterministic, so
    identical to the retired inline set). ``None`` = an inert (all-null) row;
    ``()`` = the constraint-free Total row."""
    preds: dict[str, RowPredicate | None] = {}
    for ref, row in terms.items():
        if ref == "0070":
            preds[ref] = grades_pred()
        elif row is None:
            preds[ref] = None
        else:
            preds[ref] = RowPredicate(equals=row) if row else RowPredicate()
    return preds


def ccf_row_expr(cols: set[str], framework: str) -> pl.Expr | None:
    """Each leg's conversion-factor row on ``framework``'s layout; ``None`` where
    the layout has no such rows (CRR) or the frame no conversion-factor carrier."""
    if framework != c02_rows.FRAMEWORK_BASEL_3_1:
        return None
    return of08_01_ccf_row_expr(cols)


def ccf_row_exprs(cols: set[str], framework: str) -> list[pl.Expr]:
    """The derived ``CCF_ROW`` column, where ``ccf_row_expr`` gives one."""
    expr = ccf_row_expr(cols, framework)
    return [] if expr is None else [expr.alias(CCF_ROW)]


def warn_if_unbucketed(frame: pl.DataFrame, framework: str) -> None:
    """Log a WARNING when off-balance-sheet gross (column 0020 of row 0030) on
    the obligors' own book is in no conversion-factor row.

    ``frame`` is the prepared IRB population (``c08_bs`` and ``CCF_ROW`` derived).
    Two causes, one message each: no conversion-factor carrier at all, or a
    factor that is no Table A1 factor and no own estimate. Quiet when there is
    no off-balance-sheet money to describe (LESSONS B1), and under CRR.
    """
    cols = set(frame.columns)
    if framework != c02_rows.FRAMEWORK_BASEL_3_1 or not {_BS_SIDE, _OFF_BS_GROSS} <= cols:
        return
    off = frame.filter(pl.col(_BS_SIDE) == _OFF)
    if BASIS.pop_origin in cols:
        off = off.filter(pl.col(BASIS.pop_origin))
    if CCF_ROW not in cols:
        missing = float(off.get_column(_OFF_BS_GROSS).sum() or 0.0)
        reason = f"the ledger carries no conversion-factor column ({', '.join(CCF_CARRIERS)})"
    else:
        missing = float(
            off.filter(pl.col(CCF_ROW).is_null()).get_column(_OFF_BS_GROSS).sum() or 0.0
        )
        reason = "their conversion factor is no Table A1 factor and no own estimate"
    if missing > 0:
        logger.warning(
            "OF 08.01: %.2f of off-balance-sheet exposure is in row 0030 and in no "
            "conversion-factor row (0031-0035, 0001): %s",
            missing,
            reason,
        )


def inflow_context(inflow: InflowBreakdown | None) -> ReportingContext:
    """The ``ReportingContext`` carrying one sheet's substitution inflow, on every
    axis C 08.01 decomposes it along (``INFLOW_KEYS``)."""
    if inflow is None:
        return ReportingContext(
            substitution_inflow=0.0,
            substitution_inflow_on_bs=0.0,
            substitution_inflow_off_bs=0.0,
            substitution_inflow_graded=0.0,
            substitution_inflow_slotting=0.0,
        )
    return ReportingContext(
        substitution_inflow=inflow.total,
        substitution_inflow_on_bs=inflow.on_bs,
        substitution_inflow_off_bs=inflow.off_bs,
        substitution_inflow_graded=inflow.graded,
        substitution_inflow_slotting=inflow.slotting,
        substitution_inflow_by_ccf=inflow.off_bs_by_ccf_row,
    )


def inflow_rows(inflow: InflowBreakdown | None) -> frozenset[str]:
    """The C 08.01 rows carrying a NON-ZERO inflow component on this sheet.

    ``_null_empty_rows`` renders a row all-null when its subset is empty, which is
    right for a row with nothing in it — but a row that receives an inflow is not
    empty, it is made entirely of money that lives in other sheets. Nulling it
    would delete the very component the published row sums need (and does, on an
    inflow-only sheet, where every constrained subset is empty). So the rows with
    a live inflow component are exempted."""
    if inflow is None:
        return frozenset()
    parts = {
        "0010": inflow.total,
        "0020": inflow.on_bs,
        "0030": inflow.off_bs,
        "0070": inflow.graded,
        "0080": inflow.slotting,
        **inflow.off_bs_by_ccf_row,
    }
    # Gated on the bound key set, so a component with no bound row keeps the
    # ordinary empty-row policy rather than being exempted from a pass it does
    # not need.
    return frozenset(ref for ref, value in parts.items() if value and ref in INFLOW_KEYS)


def _balance_sheet_terms(ref: str) -> RowTerms | None:
    """Section 2: on / off balance sheet, and the off-BS conversion-factor rows."""
    if ref == "0020":
        return ((_BS_SIDE, "on"),)
    if ref == "0030":
        return ((_BS_SIDE, _OFF),)
    if ref in OF08_01_CCF_ROWS:
        return ((_BS_SIDE, _OFF), (CCF_ROW, ref))
    return None
