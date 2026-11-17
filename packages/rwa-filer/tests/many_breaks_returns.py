"""
A return that breaks one published rule more times than a report records.

OF 08.01's RWEA after adjustments (c0260) is reported as 999,000 where the only
part reported (c0251, RWEA before adjustments) is 100, on four rows of three
sheets. ``boe_b0751`` — c0260 equals the sum of c0251 to c0254 — breaks once
per row and sheet: twelve times, more than ``MAX_FAILURES``.

A rule's evaluations run in place order, row first, so the first breaks a
report records are row 0001 on each sheet. A view or report that shows only
those never reaches the rows below; these returns are what proves one that
claims to show every break does.
"""

from __future__ import annotations

from typing import Final

#: The rule the return breaks on every row of every sheet.
RULE: Final = "boe_b0751"
TABLE: Final = "OF08.01.01.01"
#: The cell the rule's left-hand side reads: RWEA after adjustments.
COLUMN: Final = "0260"
SHEETS: Final = ("0001", "0002", "0010")
ROWS: Final = ("0001", "0010", "0020", "0070")
#: Every place the rule breaks, as the engine names a place.
PLACES: Final = tuple(f"row {row}, sheet {sheet}" for row in ROWS for sheet in SHEETS)

UNADJUSTED_CSV: Final = "table,sheet,row,column,value\n" + "".join(
    f"{TABLE},{sheet},{row},0251,100\n{TABLE},{sheet},{row},{COLUMN},999000\n"
    for sheet in SHEETS
    for row in ROWS
)
