"""
OF 07.00 — the cells the published template does not have.

Pipeline position:
    corep/templates.py (rows, columns) -> here (which intersections are grey)
        -> corep/c07.py::c07_plans (carried on every ``SheetPlan``)
        -> corep/postpass.py::blank_unreported_cells (the last pass)

Key responsibilities:
- Declare, row group by row group, the cells PS1/26 Annex I greys out on
  OF 07.00. The Bank of England taxonomy (v4.1.1, tables OF07.00.01.01 .. .05)
  holds no data point for a greyed cell, so a return cannot carry a figure
  there.

Why a declaration and not a property of the cell specs: the generator computes
every cell of a row, because a later cell is often a formula over an earlier
one — col 0150 on a risk-weight row is reached through that row's col 0100
inflow and col 0110. A greyed cell is therefore computed and then not
reported; what is not reported is stated here, once.

Why it can be trusted: ``tests/contracts/test_of07_published_cells.py`` holds
the declaration EXACTLY to the taxonomy, in both directions. It may neither
leave a cell the template lacks (a figure that cannot be filed) nor blank one
it has (a figure silently lost).

Recorded history (2026-11-13). Until this module existed the Basel 3.1 layout
reported three families of figure in grey cells — the CRM substitution block
on the risk-weight rows, the pre-conversion columns on the
counterparty-credit-risk rows, and col 0211 on rows that are neither — and
declared a column, 0020 "Exposures deducted from own funds" (plan item P2.12),
that OF 07.00 does not have; Annex II §3.2.2 ¶48(b) puts such exposures outside
the template altogether.

Scope: Basel 3.1 only. The CRR layout declares nothing: no EBA template or
taxonomy is held to read its grey cells from, and a guess would blank real
figures. Sheet scope is declared for the Total sheet alone
(``get_c07_rows_not_on_total``): which CLASS sheets carry the memorandum rows
is the open question recorded as P1.377.

References:
- PRA PS1/26 Annex I (OF 07.00 template); Annex II §3.2.2 ¶48, §3.2.5
- Bank of England Banking Taxonomy v4.1.1, module PRA001
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

from rwa_calc.reporting.corep.templates import B31_SA_ROW_SECTIONS

if TYPE_CHECKING:
    from collections.abc import Mapping

# The template's own column groups, so each row group below reads as the
# published template does.
_PRE_CRM_COLS: tuple[str, ...] = ("0010", "0030", "0035", "0040")
_CRM_BLOCK_COLS: tuple[str, ...] = (
    "0050",
    "0060",
    "0070",
    "0080",
    "0090",
    "0100",
    "0110",
    "0120",
    "0130",
    "0140",
)
_E_STAR_COL: tuple[str, ...] = ("0150",)
_CCF_COLS: tuple[str, ...] = ("0160", "0170", "0171", "0180", "0190")
_CCR_COL: tuple[str, ...] = ("0210",)
_CCR_EXCL_CCP_COL: tuple[str, ...] = ("0211",)
_ECAI_COLS: tuple[str, ...] = ("0230", "0235", "0240")
_CENTRAL_GOVT_DERIVED_COL: tuple[str, ...] = ("0240",)

# Rows the groups name individually. The risk-weight, CIU and memorandum rows
# are read off the row sections, so a row added to one of those axes is covered
# without being listed again.
_TOTAL_ROW: str = "0010"
_ON_BALANCE_SHEET_ROW: str = "0070"
_OFF_BALANCE_SHEET_ROW: str = "0080"
_SME_AND_SPECIALISED_LENDING_ROWS: tuple[str, ...] = (
    "0020",
    "0021",
    "0022",
    "0023",
    "0024",
    "0025",
    "0026",
)
_CCR_NETTING_SET_ROWS: tuple[str, ...] = ("0090", "0110", "0130")
_CCR_QCCP_ROWS: tuple[str, ...] = ("0100", "0120")
_RW_ROW_WITHOUT_PRE_CRM: str = "0210"
_FIRST_BLOCK_SECTION: int = 0
_RW_SECTION: int = 2
_CIU_SECTION: int = 3
_MEMORANDUM_SECTION: int = 4

_ROWS_NOT_ON_TOTAL: frozenset[str] = frozenset({"0371", "0372", "0373", "0374"})

_NOTHING: Mapping[str, frozenset[str]] = {}


def get_c07_rows_not_on_total(framework: str = "CRR") -> frozenset[str]:
    """Row refs the published template does not carry on its Total sheet.

    The four equity-transitional memorandum rows are published for the equity
    exposure class alone (Annex II ¶55A: "Firms shall only report the memorandum
    items in rows 0371-0374 for the following exposure class: (a) subordinated
    debt, equity and other own funds instruments"), so the Total sheet has no
    cell for them. Empty for CRR (module docstring, "Scope").
    """
    return _ROWS_NOT_ON_TOTAL if framework == "BASEL_3_1" else frozenset()


def get_c07_unreported_cells(framework: str = "CRR") -> Mapping[str, frozenset[str]]:
    """Row ref -> the column refs the published template has no cell for.

    Empty for CRR (module docstring, "Scope").
    """
    return _of07_unreported_cells() if framework == "BASEL_3_1" else _NOTHING


@cache
def _of07_unreported_cells() -> Mapping[str, frozenset[str]]:
    """The OF 07.00 grey cells, read top to bottom of the published template.

    - Total row 0010 and the CIU rows: every column but 0211, which breaks down
      the counterparty-credit-risk rows and the risk-weight rows only.
    - The "of which" rows of the first block (defaulted, real estate, permanent
      partial use, roll-out): no 0211 and no ECAI breakdown of the RWEA. The SME
      and specialised-lending rows keep 0230/0235 and lose only 0240.
    - On-balance-sheet row 0070: no conversion-factor breakdown (there is
      nothing to convert), no CCR columns, no ECAI breakdown. Off-balance-sheet
      row 0080 keeps the conversion-factor breakdown.
    - The CCR rows 0090-0130 report the exposure value and the RWEA and nothing
      before them: cols 0200, 0210 and 0220, plus 0211 on the three netting-set
      rows (an "of which: centrally cleared through a QCCP" row cannot exclude
      what it consists of).
    - The risk-weight rows: no CRM substitution block. The 70% row additionally
      has no pre-CRM columns.
    - The memorandum rows: no CRM block, no 0211, no ECAI breakdown.
    """
    sections = B31_SA_ROW_SECTIONS
    blank: dict[str, frozenset[str]] = {}
    for row in sections[_FIRST_BLOCK_SECTION].rows:
        blank[row.ref] = frozenset(_CCR_EXCL_CCP_COL + _ECAI_COLS)
    blank[_TOTAL_ROW] = frozenset(_CCR_EXCL_CCP_COL)
    for ref in _SME_AND_SPECIALISED_LENDING_ROWS:
        blank[ref] = frozenset(_CCR_EXCL_CCP_COL + _CENTRAL_GOVT_DERIVED_COL)
    blank[_ON_BALANCE_SHEET_ROW] = frozenset(_CCF_COLS + _CCR_COL + _CCR_EXCL_CCP_COL + _ECAI_COLS)
    blank[_OFF_BALANCE_SHEET_ROW] = frozenset(_CCR_COL + _CCR_EXCL_CCP_COL + _ECAI_COLS)
    before_exposure_value = _PRE_CRM_COLS + _CRM_BLOCK_COLS + _E_STAR_COL + _CCF_COLS + _ECAI_COLS
    for ref in _CCR_NETTING_SET_ROWS:
        blank[ref] = frozenset(before_exposure_value)
    for ref in _CCR_QCCP_ROWS:
        blank[ref] = frozenset(before_exposure_value + _CCR_EXCL_CCP_COL)
    for row in sections[_RW_SECTION].rows:
        blank[row.ref] = frozenset(_CRM_BLOCK_COLS)
    blank[_RW_ROW_WITHOUT_PRE_CRM] = frozenset(_CRM_BLOCK_COLS + _PRE_CRM_COLS)
    for row in sections[_CIU_SECTION].rows:
        blank[row.ref] = frozenset(_CCR_EXCL_CCP_COL)
    for row in sections[_MEMORANDUM_SECTION].rows:
        blank[row.ref] = frozenset(_CRM_BLOCK_COLS + _CCR_EXCL_CCP_COL + _ECAI_COLS)
    return blank
