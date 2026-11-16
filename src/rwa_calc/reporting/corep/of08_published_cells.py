"""
OF 08.01 — the cells each published sheet does not have.

Pipeline position:
    corep/templates.py (rows, columns) -> here (which intersections are grey, per sheet)
        -> corep/c08.py::c08_01_plans (carried on every ``SheetPlan``)
        -> corep/c08_sheets.py::reported_sheets (blanked, Totals included, AFTER
           the Totals are built)

Key responsibilities:
- Declare, row group by row group, the OF 08.01 cells the PRA001 taxonomy holds
  no data point for (v4.1.1, tables ``OF08.01.01.01`` and ``.02``, which
  partition one template's columns). A return cannot carry a figure there.
- Declare the seven positions whose reportability depends on the sheet.

Why a declaration and not a property of the cell specs: the generator computes
every column on every active row, because a cell is often a formula over
another — column 0090 is the waterfall over 0020, 0035, 0070 and 0080 on every
row, whether or not that row publishes 0035 — and a Total is the sum of its
class sheets. A grey cell is therefore computed and then not reported; what is
not reported is stated here, once. The OF 07.00 declaration
(``corep/of07_published_cells.py``) is the same shape for the same reason.

Why it can be trusted: ``tests/contracts/test_of08_published_cells.py`` holds
the declaration EXACTLY to the taxonomy, sheet by sheet and in both directions.
It may neither leave a cell the sheet lacks (a figure that cannot be filed) nor
blank one it has (a figure silently lost).

The sheet-dependent positions (``_ONLY_ON_SHEETS`` / ``_NOT_ON_SHEETS``):

- r0080 c0251 / c0252 on sheets 0002 and 0010, and r0170 c0251 on sheets 0001
  and 0002 — the Bank's known-issues log item 17 ("Incorrect data modelling and
  rendering of greyed-out cells"), "Amended in release 4.1.1". The annotated
  template still greys them on every sheet; the taxonomy is what is filed.
- r0017 and r0020 c0035 are NOT on sheet 0019 (Retail - secured by commercial
  immovable property non-SME). Known-issues log item 25 (19.10.2026): they are
  "erroneously greyed out in sheet 0019 ... As an interim solution, the PRA
  requests that firms report this data in the total AIRB sheet s0001 but do not
  report it separately until the next taxonomy update turns these cells into
  reportable fields." That is why the blanking runs after the Totals are built:
  sheet 0019's netting stays in Total 0001 and leaves sheet 0019 alone.
- r0017 c0310 on sheet 0010 only and r0180 c0030 on sheet 0016 only — in the
  linkbase, greyed in the annotated template, not in the log. The taxonomy is
  followed.

Scope: Basel 3.1 only, as for OF 07.00. The CRR layout declares nothing: no EBA
taxonomy is held to read its grey cells from, and a guess would blank real
figures. A sheet key with no published code (an off-axis pair, ``irb_sheets``)
has no published grid of its own and loses only what no sheet can carry.

References:
- PRA PS1/26 Annex I (OF 08.01 template); Annex II §3.3.2-§3.3.3
- Bank of England Banking Taxonomy v4.1.1, module PRA001; known-issues log
  (November 2026), items 17 and 25
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING, Final

from rwa_calc.reporting.corep.irb_sheets import B31_SHEET_KEYS

if TYPE_CHECKING:
    from collections.abc import Mapping

# The template's own column groups, so each row group below reads as the
# published template does.
_PD: Final[tuple[str, ...]] = ("0010",)
#: The four "of which: large financial sector entities ..." columns.
_LFSE: Final[tuple[str, ...]] = ("0030", "0140", "0240", "0270")
_NETTING: Final[tuple[str, ...]] = ("0035",)
_INFLOW: Final[tuple[str, ...]] = ("0080",)
_SLOTTING_FCCM: Final[tuple[str, ...]] = ("0101", "0102", "0103", "0104")
_BEFORE_EXPOSURE_VALUE: Final[tuple[str, ...]] = (
    "0020",
    "0030",
    "0035",
    "0040",
    "0050",
    "0060",
    "0070",
    "0080",
    "0090",
    *_SLOTTING_FCCM,
)
#: The off-balance-sheet and counterparty-credit-risk "of which" columns
#: (table ``OF08.01.01.02``).
_OFF_BS_OF_WHICH: Final[tuple[str, ...]] = ("0100", "0120")
_CCR_OF_WHICH: Final[tuple[str, ...]] = ("0130",)
_DEFAULTED: Final[tuple[str, ...]] = ("0125", "0265")
_CRM_IN_LGD: Final[tuple[str, ...]] = (
    "0150",
    "0160",
    "0170",
    "0171",
    "0172",
    "0173",
    "0180",
    "0190",
    "0200",
    "0210",
)
_LGD_AND_MATURITY: Final[tuple[str, ...]] = ("0230", "0250")
_POST_MODEL_ADJUSTMENT: Final[tuple[str, ...]] = ("0252",)
_FLOOR_AND_UNRECOGNISED: Final[tuple[str, ...]] = ("0253", "0254")
_OUTPUT_FLOOR: Final[tuple[str, ...]] = ("0275", "0276")
_EXPECTED_LOSS: Final[tuple[str, ...]] = ("0280", "0281", "0282")
_PRE_CREDIT_DERIVATIVES: Final[tuple[str, ...]] = ("0310",)
_OF_WHICH: Final[tuple[str, ...]] = _LFSE + _OFF_BS_OF_WHICH + _CCR_OF_WHICH + _DEFAULTED

# Rows the groups name.
_ON_BALANCE_SHEET_ROW: Final = "0020"
_ON_BALANCE_SHEET_OF_WHICH_ROW: Final = "0017"
_OFF_BALANCE_SHEET_ROW: Final = "0030"
_CCF_BUCKET_ROWS: Final[tuple[str, ...]] = ("0031", "0032", "0001", "0033", "0034", "0035")
_CCR_ROWS: Final[tuple[str, ...]] = ("0040", "0050", "0060")
_GRADES_ROW: Final = "0070"
_SLOTTING_ROW: Final = "0080"
_FREE_DELIVERIES_ROW: Final = "0170"
_DILUTION_ROW: Final = "0175"
_ALTERNATIVE_TREATMENT_ROW: Final = "0180"
_UNRATED_CORPORATE_ROWS: Final[tuple[str, ...]] = ("0190", "0200")

#: (row, column) -> the published sheet codes that HAVE the cell (module docstring).
_ONLY_ON_SHEETS: Final[dict[tuple[str, str], frozenset[str]]] = {
    ("0017", "0310"): frozenset({"0010"}),
    ("0080", "0251"): frozenset({"0002", "0010"}),
    ("0080", "0252"): frozenset({"0002", "0010"}),
    ("0170", "0251"): frozenset({"0001", "0002"}),
    ("0180", "0030"): frozenset({"0016"}),
}
#: (row, column) -> the published sheet codes that LACK the cell (known-issues 25).
_NOT_ON_SHEETS: Final[dict[tuple[str, str], frozenset[str]]] = {
    ("0017", "0035"): frozenset({"0019"}),
    ("0020", "0035"): frozenset({"0019"}),
}

_CODE_BY_KEY: Final[dict[str, str]] = {key: code for code, key in B31_SHEET_KEYS.items()}

_NOTHING: Final[Mapping[str, frozenset[str]]] = {}


def get_c08_01_unreported_cells(framework: str, sheet_key: str) -> Mapping[str, frozenset[str]]:
    """Row ref -> the column refs OF 08.01 sheet ``sheet_key`` has no cell for.

    ``sheet_key`` is our key for the sheet — a class sheet or a Total
    (``irb_sheets.B31_SHEET_KEYS``). A key no published code names gets the
    cells no sheet has. Empty for CRR (module docstring, "Scope").
    """
    if framework != "BASEL_3_1":
        return _NOTHING
    return _of08_01_unreported_cells(_CODE_BY_KEY.get(sheet_key))


@cache
def _of08_01_unreported_cells(code: str | None) -> Mapping[str, frozenset[str]]:
    """The grey cells of the sheet published as ``code`` (``None``: off the axis)."""
    blank = {ref: set(columns) for ref, columns in _on_no_sheet().items()}
    for (ref, column), codes in _ONLY_ON_SHEETS.items():
        if code is not None and code not in codes:
            blank.setdefault(ref, set()).add(column)
    for (ref, column), codes in _NOT_ON_SHEETS.items():
        if code in codes:
            blank.setdefault(ref, set()).add(column)
    return {ref: frozenset(columns) for ref, columns in blank.items() if columns}


@cache
def _on_no_sheet() -> Mapping[str, frozenset[str]]:
    """The cells no sheet of OF 08.01 has, read top to bottom of the template.

    - Total row 0010: every column.
    - On-balance-sheet rows 0017 / 0020: none of the "of which" breakdowns. Row
      0017 has no output-floor columns either; row 0020 no RWEA pre credit
      derivatives (0310), which the template reports on the Total row only.
    - Off-balance-sheet row 0030 and its conversion-factor buckets: no "of
      which", no 0310 and no on-balance-sheet netting (0035); the buckets have
      no output-floor columns.
    - Counterparty-credit-risk rows 0040-0060: the exposure value onwards only —
      nothing before it, no "of which", no output-floor columns.
    - Obligor-grade row 0070: no defaulted exposure value (0125) and no 0310.
    - Slotting row 0080: no PD, LGD or maturity, no CRM-in-LGD block, no
      inflow, no output-floor columns, no adjustments but 0251 / 0252 (and those
      on two sheets only), no "of which" but the off-balance-sheet ones.
    - Free deliveries 0170, dilution 0175, alternative treatment 0180 and the
      unrated-corporate rows 0190 / 0200: the columns each row's own measure
      needs, as the template greys the rest.
    """
    blank: dict[str, frozenset[str]] = {}
    blank[_ON_BALANCE_SHEET_OF_WHICH_ROW] = frozenset(_OF_WHICH + _OUTPUT_FLOOR)
    blank[_ON_BALANCE_SHEET_ROW] = frozenset(_OF_WHICH + _PRE_CREDIT_DERIVATIVES)
    blank[_OFF_BALANCE_SHEET_ROW] = frozenset(_OF_WHICH + _PRE_CREDIT_DERIVATIVES + _NETTING)
    for ref in _CCF_BUCKET_ROWS:
        blank[ref] = frozenset(_OF_WHICH + _PRE_CREDIT_DERIVATIVES + _NETTING + _OUTPUT_FLOOR)
    for ref in _CCR_ROWS:
        blank[ref] = frozenset(_BEFORE_EXPOSURE_VALUE + _OF_WHICH + _OUTPUT_FLOOR)
    blank[_GRADES_ROW] = frozenset(("0125", *_PRE_CREDIT_DERIVATIVES))
    blank[_SLOTTING_ROW] = frozenset(
        _PD
        + _LFSE
        + _INFLOW
        + _DEFAULTED
        + _CRM_IN_LGD
        + _LGD_AND_MATURITY
        + _FLOOR_AND_UNRECOGNISED
        + _OUTPUT_FLOOR
        + _PRE_CREDIT_DERIVATIVES
    )
    blank[_FREE_DELIVERIES_ROW] = frozenset(
        _PD
        + _LFSE
        + _DEFAULTED
        + _CRM_IN_LGD
        + _LGD_AND_MATURITY
        + _POST_MODEL_ADJUSTMENT
        + _FLOOR_AND_UNRECOGNISED
        + _OUTPUT_FLOOR
        + _EXPECTED_LOSS
        + _PRE_CREDIT_DERIVATIVES
    )
    blank[_DILUTION_ROW] = frozenset(
        _LFSE + _OFF_BS_OF_WHICH + _SLOTTING_FCCM + _DEFAULTED + _PRE_CREDIT_DERIVATIVES
    )
    blank[_ALTERNATIVE_TREATMENT_ROW] = frozenset(
        ("0140", "0240", "0270")
        + _OFF_BS_OF_WHICH
        + _SLOTTING_FCCM
        + _DEFAULTED
        + _OUTPUT_FLOOR
        + _PRE_CREDIT_DERIVATIVES
    )
    for ref in _UNRATED_CORPORATE_ROWS:
        blank[ref] = frozenset(
            _OFF_BS_OF_WHICH + _SLOTTING_FCCM + _DEFAULTED + _PRE_CREDIT_DERIVATIVES
        )
    return blank
