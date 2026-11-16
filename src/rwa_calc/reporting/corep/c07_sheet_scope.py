"""
C 07.00 / OF 07.00 sheet scope — which sheet a figure is reported on, and the Total.

Pipeline position:
    corep/c07.py::c07_plans (``memo_key_exprs`` / ``memo_axis`` /
        ``memo_sheet_frame`` / ``sheet_unreported``)
        -> cellspec.execute per sheet -> ``null_empty_rows_by_population``
        -> ``publish_sheets`` (the Total first, then what each sheet publishes)
        -> COREPTemplateBundle.c07_00

Key responsibilities:
- Place OF 07.00 memorandum rows 0300 / 0320 on the sheet of the class an
  exposure in default would otherwise have had (Basel 3.1).
- Build the Total sheet, the cell-by-cell sum of the class sheets
  (``c07_total_sheet``), from the sheets BEFORE their sheet scope is applied.
- Leave out of each sheet what the published template has no cell for.

ROWS 0300 / 0320 ARE THE "IN DEFAULT" CLASS, SPLIT BY THE CLASS BEFORE DEFAULT.
PS1/26 Annex II (ps1-26-annex-ii-reporting-instructions.pdf), row 0320 (p.97):
"Exposures included in the exposure class 'exposures in default', subject to
Article 127(1)(a) ..., which would otherwise have been assigned to the exposure
class being reported on if they were not in default" — row 0300 the same for
Art. 127(1)(b) and (3). ¶54 (pp.78-79): "Exposures shall be reported in these rows
where the obligors would have been reported in the exposure classes [...] if those
exposures were not assigned to the exposure classes 'in default'. The figures
reported, however, are the same as used to calculate the risk-weighted exposure
amounts in the exposure class 'exposures in default'." The Bank's taxonomy
(v4.1.1, table OF07.00.01.03) carries the rows on the Total and on the class
sheets of ¶52 (a)-(f), with the dimension "Exposure class before reassignment"
on each class sheet, and on no other sheet: not on the "in default" sheet, whose
figure the Total's data point already is (¶55's "in the total and in the exposure
class 'in default'" is that one data point), and not on real estate, ¶52 (g),
for which the table has no sheet. The PRA's interim answer to that gap (Bank of
England known-issues log, November 2026, issue #27, 19.10.2026): "As a temporary
solution, the PRA requests that firms report exposures assigned to the real estate
exposure class in the total sheet s0001 for rows 0300 and 0320 but do not report
such exposures separately to this, until the missing sheet 0010 is provided in
the next taxonomy update." The published set is declared in
``of07_published_cells.py``, held to the taxonomy by
``tests/contracts/test_of07_published_cells.py``.

HOW. The aggregator seals ``reporting_class_pre_default`` — the applied class
with the default limb left out (``_add_exposure_class_applied``). Each leg gets ONE
memorandum key: the sheet of that class where the template publishes rows 0300 /
0320 on it, else the "in default" sheet itself (real estate, an MDB, an
international organisation, an unknown class). On sheet K the flags
``c07_memo_origin`` / ``c07_memo_post`` mark the legs in the "in default" class on
that basis whose key is K, and rows 0300 / 0320 read those two flags where every
other row reads the sheet's own basis flags. A memorandum leg rides in the sheet
frame with both basis flags False, so no other cell can read it, and the empty-row
pass counts the other rows over the sheet's own legs alone — otherwise a memo leg
would turn the class sheet's 150% row into a row of zeros. A class with no
exposure of its own still opens its sheet for the memorandum row; its Total row
then reports zeros, as an inflow-only sheet's does.

THE TOTAL IS SUMMED BEFORE THE SCOPE. The memorandum keys partition the "in
default" legs, so the class sheets' rows 0300 / 0320 add up to every such leg
exactly once — but only before the rows are left out of the sheets that do not
publish them. Summed after, the Total would lose the real-estate-origin legs the
PRA asks to be reported there; summed from a frame that also counted them on the
"in default" sheet, it would count a defaulted corporate loan twice.

CRR is untouched: its rows 0290-0320 have their own definitions (the CRR half of
P1.377) and no taxonomy is held to scope them, so no memorandum key is derived and
no sheet scope is declared. A Basel 3.1 frame that seals no
``reporting_class_pre_default`` (a synthetic unit frame) keeps rows 0300 / 0320 on
the legs' own sheet, and the sheet scope still leaves them off a sheet that does
not publish them.

References:
- PRA PS1/26 Annex II §3.2.2 ¶47, §3.2.5 ¶52-55 (pp.78-79), rows 0300 / 0320
  (p.97); PS1/26 Art. 112(1)(j), Art. 127
- Bank of England Banking Taxonomy v4.1.1, table OF07.00.01.03; known-issues log
  (November 2026), issue #27; ``boe_b0713`` (the Total)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
from watchfire import cites

from rwa_calc.contracts.edges import REPORTING_CLASS_PRE_DEFAULT_COL
from rwa_calc.reporting.cellspec import RowPredicate
from rwa_calc.reporting.corep.of07_published_cells import (
    get_c07_memo_default_sheet_keys,
    get_c07_rows_not_on_sheet,
    get_c07_rows_not_on_total,
    get_c07_unreported_cells,
)
from rwa_calc.reporting.corep.postpass import blank_unreported_cells, null_empty_rows
from rwa_calc.reporting.corep.templates import C07_00_SA_SHEET_MAP, get_c07_columns
from rwa_calc.reporting.kernel import TwoBasis, sheet_frame

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from rwa_calc.reporting.plans import SheetPlan

#: The sheet a memorandum leg's rows 0300 / 0320 are read on (module docstring).
MEMO_KEY_COL: str = "c07_memo_key"
#: Per sheet: in the "in default" class on the origin / post basis, keyed here.
MEMO_ORIGIN_COL: str = "c07_memo_origin"
MEMO_POST_COL: str = "c07_memo_post"
#: Either of the two — the row term that marks rows 0300 / 0320 as memorandum rows.
MEMO_COL: str = "c07_memo"
MEMO_TERM: tuple[str, bool] = (MEMO_COL, True)

# Article 112(1)(j), read back from the sheet map so the key cannot drift from it.
_IN_DEFAULT_SHEET_KEY: str = C07_00_SA_SHEET_MAP["defaulted"]
_LABEL_COLS: tuple[str, str] = ("row_ref", "row_name")

_Terms = tuple[tuple[str, str | bool], ...]


@cites("PS1/26, paragraph 1.3")
def publish_sheets(
    computed: Mapping[str, pl.DataFrame],
    plans: Mapping[str, SheetPlan],
    framework: str,
) -> tuple[dict[str, pl.DataFrame], pl.DataFrame | None]:
    """The class sheets as published, and the Total summed from them first.

    ``computed`` is each sheet after execution, the empty-row pass and the sign
    convention. The Total is built from those frames with only the cell-level grey
    cells blanked; each class sheet then drops what its plan does not publish
    (``SheetPlan.unreported``) — see the module docstring for why in that order.
    """
    grey = get_c07_unreported_cells(framework)
    total = c07_total_sheet(
        {key: blank_unreported_cells(frame, grey) for key, frame in computed.items()}, framework
    )
    sheets = {
        key: blank_unreported_cells(frame, plans[key].unreported) for key, frame in computed.items()
    }
    return sheets, total


@cites("PS1/26, paragraph 1.3")
def c07_total_sheet(sheets: Mapping[str, pl.DataFrame], framework: str) -> pl.DataFrame | None:
    """The Total sheet (published z-code 0001): the class sheets, added up.

    Annex II §3.2.2 ¶47: "The information in OF CR SA is required for the total
    exposure across all exposure classes and individually for each of the
    exposure classes ... The total figures as well as the information of each
    exposure class shall be reported in a separate dimension." ``None`` when
    ``sheets`` is empty.

    A CELL-BY-CELL SUM OF THE CLASS SHEETS, not a second execution over the
    whole population. Every row is evaluated per sheet over that sheet's own
    population — the real-estate rows exist on the real-estate sheet alone, an
    inflow lands on the protection provider's sheet, each cell reads its own
    basis — so the sum of the sheets is the only total consistent with them, and
    it is what the published rule states (``boe_b0713``: sheet 0001 equals the
    sum of sheets 0002-0017). A cell no sheet reports is EMPTY on the Total, not
    zero: a sum over nothing is not a measured figure, and a grey cell stays
    grey. A sheet outside the published axis (``c07_plans`` records it as an
    error) is still part of the total exposure and is included.

    ``publish_sheets`` hands it the class sheets BEFORE their own sheet scope is
    applied, so a figure the template publishes on the Total alone — rows 0300 /
    0320 of a real-estate-origin exposure in default — is in it. The rows the
    published Total does not carry are blanked (``get_c07_rows_not_on_total``).
    """
    if not sheets:
        return None
    stacked = pl.concat(list(sheets.values()), how="vertical_relaxed")
    value_cols = [col for col in stacked.columns if col not in _LABEL_COLS]
    total = stacked.group_by("row_ref", maintain_order=True).agg(
        pl.col("row_name").first(),
        *(
            pl.when(pl.col(col).count() > 0).then(pl.col(col).sum()).alias(col)
            for col in value_cols
        ),
    )
    not_on_total = {ref: frozenset(value_cols) for ref in get_c07_rows_not_on_total(framework)}
    return blank_unreported_cells(total.select(stacked.columns), not_on_total)


@cites("PS1/26 Art. 112")
@cites("PS1/26 Art. 127")
def memo_key_exprs(framework: str, cols: set[str], key: Callable[[str], pl.Expr]) -> list[pl.Expr]:
    """The memorandum key of every leg, or nothing where it does not apply.

    ``key`` is the template's Art. 112(1) sheet-key transform (``c07``'s
    ``_art112_sheet_key_expr``), applied to the class before default: that sheet
    where the template publishes rows 0300 / 0320 on it, else the "in default"
    sheet. Empty where no such sheet is declared (CRR) and on a frame without the
    sealed column.
    """
    published = sorted(get_c07_memo_default_sheet_keys(framework))
    if not published or REPORTING_CLASS_PRE_DEFAULT_COL not in cols:
        return []
    sheet = key(REPORTING_CLASS_PRE_DEFAULT_COL)
    return [
        pl.when(sheet.is_in(published))
        .then(sheet)
        .otherwise(pl.lit(_IN_DEFAULT_SHEET_KEY))
        .alias(MEMO_KEY_COL)
    ]


def memo_terms(cols: set[str]) -> _Terms:
    """The term rows 0300 / 0320 add where a frame carries memorandum keys."""
    return (MEMO_TERM,) if MEMO_KEY_COL in cols else ()


def memo_axis(basis: TwoBasis, data: pl.DataFrame) -> set[str]:
    """The sheets the "in default" legs' memorandum keys open (none without keys)."""
    if MEMO_KEY_COL not in data.columns:
        return set()
    in_default = _in_default(basis.pop_origin, basis.class_origin) | _in_default(
        basis.pop_post, basis.class_post
    )
    return set(data.filter(in_default.fill_null(value=False))[MEMO_KEY_COL].unique().to_list())


def memo_sheet_frame(basis: TwoBasis, data: pl.DataFrame, sheet_key: str) -> pl.DataFrame:
    """One sheet's frame (``kernel.sheet_frame``) with its memorandum legs kept and flagged."""
    if MEMO_KEY_COL not in data.columns:
        return sheet_frame(basis, data, sheet_key)
    here = pl.col(MEMO_KEY_COL) == sheet_key
    flagged = data.with_columns(
        (_in_default(basis.pop_origin, basis.class_origin) & here)
        .fill_null(value=False)
        .alias(MEMO_ORIGIN_COL),
        (_in_default(basis.pop_post, basis.class_post) & here)
        .fill_null(value=False)
        .alias(MEMO_POST_COL),
    ).with_columns((pl.col(MEMO_ORIGIN_COL) | pl.col(MEMO_POST_COL)).alias(MEMO_COL))
    return sheet_frame(basis, flagged, sheet_key, keep=MEMO_COL)


def basis_flags(terms: _Terms, basis: TwoBasis) -> tuple[str, str]:
    """The origin / post flags a row's cells read: the memorandum pair on rows 0300 / 0320."""
    if MEMO_TERM in terms:
        return MEMO_ORIGIN_COL, MEMO_POST_COL
    return basis.basis_origin, basis.basis_post


def sheet_unreported(framework: str, sheet_key: str) -> Mapping[str, frozenset[str]]:
    """What one class sheet does not publish: the grey cells, and every cell of a row
    the template does not carry on that sheet (``get_c07_rows_not_on_sheet``)."""
    grey = get_c07_unreported_cells(framework)
    rows = get_c07_rows_not_on_sheet(framework, sheet_key)
    if not rows:
        return grey
    columns = frozenset(column.ref for column in get_c07_columns(framework))
    return {**grey, **dict.fromkeys(rows, columns)}


def null_empty_rows_by_population(
    frame: pl.DataFrame, plan: SheetPlan, basis: TwoBasis
) -> pl.DataFrame:
    """``postpass.null_empty_rows``, counting each row over the legs it can read.

    Rows 0300 / 0320 are counted over the whole sheet frame, memorandum legs
    included; every other row over the sheet's own legs. Without memorandum legs
    the two are one frame and this is the ordinary pass.
    """
    preds = {
        ref: None if terms is None else RowPredicate(equals=terms)
        for ref, terms in plan.row_terms.items()
    }
    memo = {ref for ref, terms in plan.row_terms.items() if terms and MEMO_TERM in terms}
    own = plan.frame.filter(pl.col(basis.basis_origin) | pl.col(basis.basis_post))
    others = {ref: pred for ref, pred in preds.items() if ref not in memo}
    frame = null_empty_rows(frame, own, others, plan.inflow_rows)
    if not memo:
        return frame
    return null_empty_rows(frame, plan.frame, {ref: preds[ref] for ref in memo})


def _in_default(population: str, class_col: str) -> pl.Expr:
    """In the "in default" class (Art. 112(1)(j)) on one basis."""
    return pl.col(population) & (pl.col(class_col) == _IN_DEFAULT_SHEET_KEY)
