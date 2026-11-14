"""
The C 08 / OF 08 sheet axis — the population, the sheet keys and the Total sheets.

Pipeline position:
    sealed aggregator-exit ledger
        -> irb_population() / sheet_keys() / inflow_sheet_key()
        -> corep/c08.py (one execution plan per sheet)
        -> with_total_sheets() (the two published Total sheets)
        -> COREPTemplateBundle

Key responsibilities:
- Select the IRB book C 08.01-08.05 report (``irb_population`` /
  ``non_slotting``).
- Key each leg to its sheet, on both bases. Basel 3.1: the published
  class-and-approach sheet (``corep/irb_sheets.py``, the definition OF 02.00
  shares). CRR: the exposure class.
- Build the two Basel 3.1 Total sheets (published codes 0001 and 0002) from the
  class sheets, and record a sheet that is not on the published axis.

THE BASEL 3.1 AXIS (recorded fix 2026-11-13). OF 08.01, 08.02, 08.03 and 08.05
are published on seventeen sheets: fifteen exposure sub-classes each under one
approach, and two Totals (Annex II §3.3.2; taxonomy table ``OF08.01.01.01``).
They were generated on sheets keyed by exposure class alone, which is coarser —
one ``corporate`` sheet answered two published sheets, one ``retail_mortgage``
sheet four — so no figure on them could be assigned to a published sheet and
filed.

CRR IS NOT RE-KEYED, AND THAT IS A DECISION. C 08.01 has its own published axis
— exposure class by own-estimates-or-not, with sovereign sheets and no
"financial and large corporates" — so it would be a second layout, not this one
reused. No EBA taxonomy is held to lay it out against: the only source is the
EBA rule extract, from which ``filing/sheet_maps.py`` reads the seventeen codes
but not their cells, so a re-key could not be held to its publisher in both
directions as the Basel 3.1 one is
(``tests/contracts/test_of08_published_sheets.py``). The filing package is
written from the PRA001 taxonomy, which is Basel 3.1 only. The CRR sheets
therefore stay keyed by exposure class, with no Total sheet, exactly as before.

SUPERVISORY SLOTTING. The slotting row (0080) "shall only apply to the exposure
sub-class 'corporate - specialised lending'" (Annex II §3.3.3), and the template
has it on two sheets: 0010 "Specialised Lending (FIRB approach or slotting
approach)" and the FIRB-and-slotting Total 0002. ``boe_b1041`` requires it to be
REPORTED on those two and ``boe_b0206`` requires it EMPTY on every other. So a
slotting leg is on sheet 0010 (``irb_sheets``), and on those two sheets row 0080
is a zero, never empty, when the firm has no slotting exposure
(``REPORTED_ROWS``). OF 08.02, 08.03 and 08.05 exclude slotting altogether
(§3.3.4 ¶77A, §3.3.5.1 ¶77), so their sheet 0010 is F-IRB specialised lending
alone.

WHAT A TOTAL SHEET CONTAINS. Annex II says only that "The Total template must be
reported for the FIRB and the slotting approaches and, separately for the AIRB
approach". The Bank's rules say what that is wherever a figure can be added up:
``boe_b0748`` — the AIRB Total equals the sum of the AIRB sheets — and
``boe_b0749`` for the FIRB-and-slotting Total, each over a listed set of
columns (``boe_b0749``'s list is the shorter: it omits seventeen of
``boe_b0748``'s, among them 0250 and 0300). So a Total is the CELL-BY-CELL SUM OF ITS
CLASS SHEETS (the C 07.00 decision, ``c07.c07_total_sheet``, for the same
reason: every row is evaluated per sheet over that sheet's own population and
basis, so the sum of the sheets is the only total consistent with them). Three
kinds of cell are not a sum:

- AN EXPOSURE-WEIGHTED AVERAGE cannot be added up. Neither rule lists PD (0010)
  or LGD (0230 / 0240). On a Total such a cell is the average over the
  exposures the Total covers that CARRY the parameter, weighted as the sheets
  weight it and measured over each sheet's own plan, so a sheet that does not
  report the cell contributes nothing to it. A leg with no value is left out,
  not averaged in as a zero: a slotting exposure has no maturity and no LGD
  (Annex II column 0250: "not be filled in ... for exposures subject to the
  slotting approach"), and on the FIRB-and-slotting Total it sits beside the
  F-IRB legs of every other sheet.
- COLUMN 0250 IS LISTED BY ``boe_b0748`` AND IS AN AVERAGE ALL THE SAME. Annex II
  defines it as the exposure-weighted average maturity in days. A sum of
  averages is not a figure, so the AIRB Total reports the average and
  ``boe_b0748`` breaks on column 0250 wherever two AIRB sheets report a
  maturity — a limit of the published rule, not a number to manufacture.
- A RATE DERIVED FROM OTHER CELLS (OF 08.05 column 0040, the observed default
  rate) is re-derived from the Total's own counts.

The obligor count (0300) is summed on both Totals: an obligor with exposures on
two sheets is counted on each, as the sheets count it. ``boe_b0748`` lists it;
``boe_b0749`` does not, and the FIRB-and-slotting Total is summed the same way
so the two Totals are one definition.

A cell no sheet reports is EMPTY on the Total, never zero. A Total is reported
only where one of its sheets is: a firm on one approach reports one Total
(Annex II §3.3.1 ¶75).

A SHEET THAT IS NOT ON THE PUBLISHED AXIS — an A-IRB institution, an IRB
sovereign (``irb_sheets``) — is still reported, is counted in its approach's
Total, and is recorded as an error on the bundle. OF 02.00's approach rows count
the same legs (``c02._warn_if_a_breakdown_strands``), and the A-IRB Total is one
data point with OF 02.00 row 0310, so leaving them out of the Total would file
one data point with two values. The published rule then says what it should:
``boe_b0748`` fails by exactly the amount Basel 3.1 has no sheet for.

A Total sheet has no execution plan: it is built from its sheets, and
``lineage.summed_sheet_reason`` tells a reader so.

References:
- PRA PS1/26 Annex II §3.3.1-§3.3.5, §3.3.7 (OF 08.01 / 08.02 / 08.03 / 08.05)
- Reg (EU) 2021/451 Annex II §3.3 (C 08.01-08.05, the CRR sheets)
- Bank of England Banking Taxonomy v4.1.1: ``boe_b0206``, ``boe_b0748``,
  ``boe_b0749``, ``boe_b0749_1``, ``boe_b1041``
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import polars as pl
from watchfire import cites

from rwa_calc.reporting.cellspec import CellSpec, Formula, Sum, TemplateSpec, WeightedAvg, execute
from rwa_calc.reporting.corep import c02_rows, irb_sheets
from rwa_calc.reporting.corep.pd_scale import UNASSIGNED, published_row_refs
from rwa_calc.reporting.corep.templates import PD_BANDS
from rwa_calc.reporting.kernel import (
    TwoBasis,
    class_keys,
    pick,
    population_flags,
)
from rwa_calc.reporting.kernel.bases import (
    ORIGIN_APPROACH_SOURCE,
    POST_APPROACH_SOURCE,
    POST_CLASS_SOURCE,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from rwa_calc.reporting.cellspec import RowPredicate
    from rwa_calc.reporting.plans import SheetPlan

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

IRB_APPROACHES: Final[tuple[str, ...]] = (
    irb_sheets.FIRB,
    irb_sheets.AIRB,
    irb_sheets.SLOTTING,
)

#: The C 08 two-basis discriminators. The mechanism — derived boolean columns
#: rather than ``RowPredicate`` fields, and why that is the only shape the post
#: basis can DEGRADE in — lives in ``reporting/kernel/bases.py``, shared with
#: C 07.00. C 08.01-03 opt into the two-basis population; C 08.04/05 keep
#: ``irb_population``'s origin-only default.
BASIS: Final = TwoBasis("c08")

#: OF 08.01 rows that are REPORTED on a sheet even with nothing in them — a
#: zero, where every other empty row is rendered empty. The slotting row, on the
#: two sheets the template has it on (module docstring).
REPORTED_ROWS: Final[dict[str, frozenset[str]]] = {
    irb_sheets.SLOTTING_SHEET_KEY: frozenset({"0080"}),
    irb_sheets.TOTAL_FIRB_SLOTTING_KEY: frozenset({"0080"}),
}

_TOTAL_KEYS: Final[tuple[str, ...]] = tuple(
    key for _code, key, _label, _tab in irb_sheets.B31_TOTAL_SHEETS
)
_TOTAL_LABELS: Final[dict[str, str]] = {
    key: label for _code, key, label, _tab in irb_sheets.B31_TOTAL_SHEETS
}

_LABEL_COLS: Final[tuple[str, str]] = ("row_ref", "row_name")

# Rows that sort after every other on a Total: the residual for a leg with no
# grade or an out-of-scale PD (the C 08.02 label and the C 08.03 / 08.05 code).
_TRAILING_ROWS: Final[frozenset[str]] = frozenset({UNASSIGNED, "9999"})


# =============================================================================
# The population
# =============================================================================


def irb_population(
    results: pl.LazyFrame, cols: set[str], *, both_bases: bool = False
) -> pl.LazyFrame:
    """The IRB book (retired _filter_by_irb_approach): F-IRB/A-IRB/slotting.

    ``both_bases`` selects WHICH IRB book. The default is the ORIGIN-approach one
    — the obligor's own book, which is what C 08.04/05 read. C 08.01/02/03
    take the UNION of it and the POST-substitution book, tagged with
    ``c08_pop_origin`` / ``c08_pop_post`` so each cell reads its own basis (see
    the ``corep/c08.py`` module docstring). A leg with no substitution is in
    both, which is why the split is number-neutral on a book that never
    substitutes.

    The post book is a SUBSET of the origin one here, unlike C 07.00's:
    ``aggregator._post_crm_approach_expr`` maps an SA guarantor to the SA literal
    and everything else to the obligor's own approach, so an IRB-origin leg can
    only LEAVE the IRB population post-substitution (to an SA guarantor) and an
    SA-origin leg can never enter it. No dedupe is needed, and the row-0070/0080
    approach-partition terms — which key ``reporting_approach_origin`` — stay a
    valid partition of the post population.
    """
    tagged = results.with_columns(population_flags(BASIS, cols, IRB_APPROACHES))
    if both_bases:
        return tagged.filter(pl.col(BASIS.pop_origin) | pl.col(BASIS.pop_post))
    return tagged.filter(pl.col(BASIS.pop_origin)).drop(BASIS.pop_origin, BASIS.pop_post)


def non_slotting(
    results: pl.LazyFrame, cols: set[str], *, both_bases: bool = False
) -> pl.LazyFrame:
    """The IRB book less supervisory slotting — what C 08.02-08.05 report."""
    irb = irb_population(results, cols, both_bases=both_bases)
    approach_col = pick(cols, "reporting_approach_origin", "approach")
    if approach_col is not None:
        return irb.filter(pl.col(approach_col) != irb_sheets.SLOTTING)
    return irb


# =============================================================================
# The sheet keys
# =============================================================================


@cites("PS1/26, paragraph 1.3")
def sheet_keys(cols: set[str], origin_class_col: str, framework: str) -> list[pl.Expr]:
    """The two sheet-key columns of a leg — the obligor's sheet and the guarantor's.

    Basel 3.1 keys the published class-and-approach sheet on each basis: the
    origin key from the obligor's own approach and class, the post key from the
    post-substitution pair, its class passed through
    ``irb_sheets.placeable_irb_class`` exactly as OF 02.00 passes it. CRR keys
    the exposure class (module docstring). C 08 applies no other key transform —
    no specialised-lending merge, unlike C 07.00.

    The post key degrades to the origin key on a frame that seals no
    post-substitution column, which is what makes the two-basis split
    number-neutral wherever nothing substitutes. Each basis reads the other's
    approach where its own is not sealed, exactly as ``population_flags`` admits
    it; a frame with no approach at all has an empty IRB population, so its keys
    are never read and it takes the class keys.
    """
    approaches = [name for name in (ORIGIN_APPROACH_SOURCE, POST_APPROACH_SOURCE) if name in cols]
    if framework != c02_rows.FRAMEWORK_BASEL_3_1 or not approaches:
        return class_keys(BASIS, cols, origin_class_col)
    origin_approach, post_approach = approaches[0], approaches[-1]
    post_class = POST_CLASS_SOURCE if POST_CLASS_SOURCE in cols else origin_class_col
    return [
        irb_sheets.sheet_key_expr(cols, pl.col(origin_approach), pl.col(origin_class_col)).alias(
            BASIS.class_origin
        ),
        irb_sheets.sheet_key_expr(
            cols,
            pl.col(post_approach),
            irb_sheets.placeable_irb_class(post_class, origin_class_col, post_approach),
        ).alias(BASIS.class_post),
    ]


def inflow_sheet_key(
    cols: set[str], origin_class_col: str, framework: str
) -> Callable[[str], pl.Expr] | None:
    """How a substitution inflow's destination class becomes a destination SHEET.

    ``None`` under CRR, where the destination is the guarantor's class. Under
    Basel 3.1 the covered part lands on the sheet its exposure value and RWEA
    land on — the post-basis key of ``sheet_keys``, read over the guarantor's
    class — so an inflow can never open a sheet of its own beside them.
    """
    if framework != c02_rows.FRAMEWORK_BASEL_3_1:
        return None
    approach = pick(cols, POST_APPROACH_SOURCE) or pick(cols, ORIGIN_APPROACH_SOURCE)
    if approach is None:
        # No approach at all: the IRB population is empty and nothing can arrive.
        return lambda _class_col: pl.lit(None, dtype=pl.String)
    return lambda class_col: irb_sheets.sheet_key_expr(
        cols,
        pl.col(approach),
        irb_sheets.placeable_irb_class(class_col, origin_class_col, approach),
    )


# =============================================================================
# The Total sheets
# =============================================================================


def c08_class_sheets(sheets: Mapping[str, pl.DataFrame]) -> dict[str, pl.DataFrame]:
    """The class sheets of an OF 08 template — everything but the two Totals.

    A Total is the sum of these, so anything that ADDS THE SHEETS UP (a tie-out
    against C 02.00 or OV1, a conservation check against the population) must
    read this view; adding the whole template counts every exposure twice.
    """
    return {key: sheet for key, sheet in sheets.items() if key not in _TOTAL_KEYS}


@cites("PS1/26, paragraph 1.3")
def with_total_sheets(
    template: str,
    sheets: dict[str, pl.DataFrame],
    plans: Mapping[str, SheetPlan],
    framework: str,
    errors: list[str],
) -> dict[str, pl.DataFrame]:
    """``sheets`` with the published Total sheets added in front (Basel 3.1).

    ``sheets`` is one template's generated class sheets and ``plans`` the plans
    they were executed from, keyed alike; ``template`` names it (``"C08.01"``)
    and selects its ``_TOTAL_POLICIES`` entry. Each Total is built from the class
    sheets that add into it (module docstring); a sheet outside the published
    axis is counted in its approach's Total and recorded on ``errors``. CRR, and
    a template that produced nothing, are returned unchanged.
    """
    if framework != c02_rows.FRAMEWORK_BASEL_3_1 or not sheets:
        return sheets
    policy = _TOTAL_POLICIES[template]
    groups: dict[str, list[str]] = {}
    for key in sheets:
        place = irb_sheets.place_of(key)
        if not place.published:
            _record_off_axis(template, key, place.total, errors)
        if place.total is not None:
            groups.setdefault(place.total, []).append(key)
    totals: dict[str, pl.DataFrame] = {}
    for total_key in _TOTAL_KEYS:
        members = [key for key in groups.get(total_key, []) if sheets[key].height > 0]
        if members:
            totals[total_key] = _total_sheet(
                [sheets[key] for key in members],
                [plans[key] for key in members],
                row_order=policy.row_order(framework),
                rederived=policy.rederived,
                zero_rows=policy.reported_rows.get(total_key, frozenset()),
            )
    return {**totals, **sheets}


# =============================================================================
# Private helpers
# =============================================================================


def _layout_order(_framework: str) -> Sequence[str]:
    """No published order to impose: every sheet of the template has one layout."""
    return ()


def _pd_band_order(_framework: str) -> Sequence[str]:
    """The C 08.02 PD-band labels in scale order (firm grades follow, as first seen)."""
    return [label for _lower, _upper, label in PD_BANDS]


@dataclass(frozen=True)
class _TotalPolicy:
    """How one template's Total sheets are built.

    Attributes:
        row_order: The published row order of a template whose sheets report
            different rows. Rows it does not name keep the order they are first
            seen in.
        rederived: Columns whose ``Formula`` cell is re-applied to the Total's
            own row instead of summed (a rate over two counts).
        reported_rows: Per Total key, the rows that are a zero and never empty.
    """

    row_order: Callable[[str], Sequence[str]] = _layout_order
    rederived: frozenset[str] = frozenset()
    reported_rows: Mapping[str, frozenset[str]] = field(default_factory=dict)


_TOTAL_POLICIES: Final[dict[str, _TotalPolicy]] = {
    "C08.01": _TotalPolicy(reported_rows=REPORTED_ROWS),
    "C08.02": _TotalPolicy(row_order=_pd_band_order),
    "C08.03": _TotalPolicy(row_order=published_row_refs),
    # Column 0040 is the observed default rate (0030 / 0020) and column 0050
    # copies it where no historical rate is supplied: rates, not amounts.
    "C08.05": _TotalPolicy(row_order=published_row_refs, rederived=frozenset({"0040", "0050"})),
}


def _record_off_axis(template: str, key: str, total_key: str | None, errors: list[str]) -> None:
    """Record a generated sheet the published axis has no code for."""
    counted = "no Total" if total_key is None else f"'{_TOTAL_LABELS[total_key]}'"
    message = (
        f"{template}: sheet '{key}' is an (approach, exposure class) pair the published "
        f"Basel 3.1 axis has no sheet for (PS1/26 Art. 147A); reported outside the "
        f"published axis and counted in {counted}"
    )
    errors.append(message)
    logger.warning("%s", message)


def _total_sheet(
    frames: list[pl.DataFrame],
    plans: list[SheetPlan],
    *,
    row_order: Sequence[str],
    rederived: frozenset[str],
    zero_rows: frozenset[str],
) -> pl.DataFrame:
    """One Total: its class sheets added up, averaged where a cell is an average."""
    schema = frames[0].schema
    value_cols = [name for name in schema if name not in _LABEL_COLS and schema[name].is_numeric()]
    sheet_rows = [{row["row_ref"]: row for row in frame.iter_rows(named=True)} for frame in frames]
    names: dict[str, str] = {}
    for rows in sheet_rows:
        for ref, row in rows.items():
            names.setdefault(ref, row["row_name"])
    averages = _averaged_cells(sheet_rows, plans)
    formulas = _formula_cells(plans, rederived)
    populated = {
        col
        for col in value_cols
        if any(row.get(col) is not None for rows in sheet_rows for row in rows.values())
    }

    out: list[dict[str, object]] = []
    for ref in _ordered(list(names), row_order):
        record: dict[str, object] = dict.fromkeys(schema)
        record["row_ref"] = ref
        record["row_name"] = names[ref]
        for col in value_cols:
            if (ref, col) in averages:
                record[col] = averages[(ref, col)]
                continue
            reported = [
                value for rows in sheet_rows if (value := rows.get(ref, {}).get(col)) is not None
            ]
            if reported:
                record[col] = float(sum(reported))
            elif ref in zero_rows and col in populated:
                record[col] = 0.0
        cells = {col: _number(record[col]) for col in value_cols}
        for col in value_cols:
            formula = formulas.get((ref, col))
            if formula is not None:
                record[col] = formula.fn(cells, False)
        for name in schema:
            if name not in _LABEL_COLS and name not in value_cols:
                record[name] = names[ref]  # the C 08.02 row label column
        out.append(record)
    return pl.DataFrame(out, schema=schema)


def _averaged_cells(
    sheet_rows: list[dict[str, dict[str, object]]], plans: list[SheetPlan]
) -> dict[tuple[str, str], float | None]:
    """Each exposure-weighted-average cell of the Total, over all its sheets.

    The average is taken over the legs the Total covers that CARRY the averaged
    parameter: per sheet, the weighted sum of the parameter and the sum of the
    weight over the legs of that cell where the parameter is reported, measured
    by executing the sheet's own plan over its own rows. A leg with no value is
    left out rather than averaged in as a zero — a slotting exposure has no
    maturity and no LGD (Annex II column 0250: "not be filled in ... for
    exposures subject to the slotting approach"), and on the FIRB-and-slotting
    Total it sits beside the F-IRB legs of every other sheet. A sheet that
    reports no value in the cell (it binds no average there, or the row is
    empty) contributes nothing.
    """
    numerators: dict[tuple[str, str], float] = {}
    denominators: dict[tuple[str, str], float] = {}
    averaged: set[tuple[str, str]] = set()
    for rows, plan in zip(sheet_rows, plans, strict=True):
        bindings = {
            address: (cell.binding, cell.predicate)
            for address, cell in plan.spec.cells.items()
            if isinstance(cell.binding, WeightedAvg)
        }
        if not bindings:
            continue
        averaged.update(bindings)
        measured = _weighted_sums(plan, bindings)
        for address in bindings:
            ref, col = address
            numerator, denominator = measured.get(address, (0.0, 0.0))
            if rows.get(ref, {}).get(col) is None or not denominator:
                continue
            numerators[address] = numerators.get(address, 0.0) + numerator
            denominators[address] = denominators.get(address, 0.0) + denominator
    return {
        address: (numerators[address] / denominators[address] if address in denominators else None)
        for address in averaged
    }


def _weighted_sums(
    plan: SheetPlan, bindings: Mapping[tuple[str, str], tuple[WeightedAvg, RowPredicate | None]]
) -> dict[tuple[str, str], tuple[float, float]]:
    """Per ``WeightedAvg`` cell of one sheet: the scaled weighted sum of its
    parameter and the sum of its weight, over the legs where the parameter is
    reported.

    Executes ``plan`` with each cell replaced by two ``Sum`` cells over derived
    columns, under the cell's own predicate — so the legs are exactly the legs
    the sheet's own cell reads.
    """
    present = set(plan.frame.columns)
    derived: dict[WeightedAvg, tuple[str, str]] = {}
    exprs: list[pl.Expr] = []
    cells: dict[tuple[str, str], CellSpec] = {}
    for (ref, col), (binding, predicate) in bindings.items():
        if binding.col not in present or binding.weight not in present:
            continue
        if binding not in derived:
            names = (f"_c08_total_n{len(derived)}", f"_c08_total_d{len(derived)}")
            weight = pl.when(pl.col(binding.col).is_not_null()).then(pl.col(binding.weight))
            exprs.append((pl.col(binding.col) * weight * binding.scale).alias(names[0]))
            exprs.append(weight.alias(names[1]))
            derived[binding] = names
        numerator, denominator = derived[binding]
        cells[(ref, f"{col}n")] = CellSpec(Sum(numerator), predicate=predicate)
        cells[(ref, f"{col}d")] = CellSpec(Sum(denominator), predicate=predicate)
    if not cells:
        return {}
    spec = TemplateSpec(
        name=plan.spec.name,
        rows=plan.spec.rows,
        column_refs=tuple(sorted({col for _row, col in cells})),
        cells=cells,
        predicate=plan.spec.predicate,
        empty_cell="zero",
    )
    executed = {
        row["row_ref"]: row
        for row in execute(spec, plan.frame.with_columns(exprs), plan.ctx).iter_rows(named=True)
    }
    return {
        (ref, col): (
            float(executed[ref].get(f"{col}n") or 0.0),
            float(executed[ref].get(f"{col}d") or 0.0),
        )
        for ref, col in bindings
        if ref in executed and f"{col}d" in executed[ref]
    }


def _formula_cells(
    plans: list[SheetPlan], rederived: frozenset[str]
) -> dict[tuple[str, str], Formula]:
    """The ``Formula`` cells a Total re-applies to its own row, by address."""
    formulas: dict[tuple[str, str], Formula] = {}
    if not rederived:
        return formulas
    for plan in plans:
        for (ref, col), cell in plan.spec.cells.items():
            if col in rederived and isinstance(cell.binding, Formula):
                formulas.setdefault((ref, col), cell.binding)
    return formulas


def _number(value: object) -> float | None:
    """A Total's cell as a formula reads it: a number, or None where empty."""
    return float(value) if isinstance(value, int | float) else None


def _ordered(rows: list[str], row_order: Sequence[str]) -> list[str]:
    """``rows`` in published order: the named order, then first seen, residual last."""
    rank = {ref: position for position, ref in enumerate(row_order)}
    seen = {ref: position for position, ref in enumerate(rows)}
    return sorted(
        rows, key=lambda ref: (ref in _TRAILING_ROWS, rank.get(ref, len(rank)), seen[ref])
    )
