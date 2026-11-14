"""
Two small returns for comparison tests, in real PRA001 cells.

Every return here is OF 07.00, the corporates sheet (0008): one 1,000,000
exposure, on the total row (0010), the on-balance-sheet row (0070) and one
risk-weight row. They differ from each other the ways two systems' returns do,
one way per builder argument, so a test names the difference it is about:

- ``risk_weight_row`` — the same exposure at 50% (row 0200) or 75% (row 0220).
  Both versions satisfy every rule linking the cells: the calculations differ.
- ``total_overlay`` — an amount added to the RWEA total (r0010 c0220) only, so
  the total no longer adds up and Bank rules break in that return alone.
- ``ecai_columns`` — RWEA "of which" columns 0230 / 0235 filled in. Without
  them boe_b0703 breaks; with them it holds.
- ``zero_where_empty`` — a zero in row 0140 (0%), which the Bank expects to be
  left empty for corporates: boe_b0441 breaks.
- ``decimals`` / ``nudge`` — the stated accuracy, and an amount added to the
  exposure columns of the risk-weight row, to probe rounding.

Values are from the packaged PRA001 rule book's own arithmetic: RWEA is
exposure x risk weight on the risk-weight row (boe_b0487 / boe_b0489), and
each total is the sum of its rows (boe_b0717, boe_b0719, boe_b0721).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl

from pack_builders import VALID_LEI
from rwa_filer.model import CanonicalReturn, ReturnHeader

TABLE = "OF07.00.01.01"
CORPORATES = "0008"
EXPOSURE = 1_000_000.0
#: The exposure columns: original, net, after CRM substitution, fully adjusted, value.
EXPOSURE_COLUMNS = ("0010", "0040", "0110", "0150", "0200")
#: Column 0110 is not reported on a risk-weight row.
RISK_WEIGHT_ROW_COLUMNS = ("0010", "0040", "0150", "0200")
RATES = {"0200": 0.5, "0220": 0.75}
HEADER = ReturnHeader(VALID_LEI, date(2027, 3, 31), "PRA001")
COLUMNS = ["table", "sheet", "open_key", "row", "column", "value", "decimals"]


def corporate_facts(  # noqa: PLR0913 - one keyword per way two returns differ
    *,
    risk_weight_row: str = "0200",
    total_overlay: float = 0.0,
    ecai_columns: bool = False,
    zero_where_empty: bool = False,
    decimals: int | None = None,
    nudge: float = 0.0,
) -> list[tuple[object, ...]]:
    """The fact rows of one corporates return."""
    rwea = EXPOSURE * RATES[risk_weight_row]
    facts: list[tuple[object, ...]] = []
    for row in ("0010", "0070"):
        facts.extend(
            (TABLE, CORPORATES, None, row, column, EXPOSURE, decimals)
            for column in EXPOSURE_COLUMNS
        )
        facts.append(
            (
                TABLE,
                CORPORATES,
                None,
                row,
                "0220",
                rwea + (total_overlay if row == "0010" else 0.0),
                decimals,
            )
        )
    facts.extend(
        (TABLE, CORPORATES, None, risk_weight_row, column, EXPOSURE + nudge, decimals)
        for column in RISK_WEIGHT_ROW_COLUMNS
    )
    facts.append((TABLE, CORPORATES, None, risk_weight_row, "0220", rwea, decimals))
    if ecai_columns:
        for row in ("0010", risk_weight_row):
            amount = rwea + (total_overlay if row == "0010" else 0.0)
            facts.append((TABLE, CORPORATES, None, row, "0230", amount, decimals))
            facts.append((TABLE, CORPORATES, None, row, "0235", 0.0, decimals))
    if zero_where_empty:
        facts.append((TABLE, CORPORATES, None, "0140", "0010", 0.0, decimals))
    return facts


def corporate_return(
    *, indicators: dict[str, bool] | None = None, **differences: Any
) -> CanonicalReturn:
    """One corporates return; ``differences`` as ``corporate_facts`` takes them."""
    frame = pl.DataFrame(corporate_facts(**differences), schema=COLUMNS, orient="row")
    return CanonicalReturn.from_frame(HEADER, frame, indicators=indicators)


def unreported_return(indicators: dict[str, bool]) -> CanonicalReturn:
    """A return with no facts, declaring ``indicators`` as given."""
    frame = pl.DataFrame(
        schema={"table": pl.String, "row": pl.String, "column": pl.String, "value": pl.Float64}
    )
    return CanonicalReturn.from_frame(HEADER, frame, indicators=indicators)


def corporate_csv(**differences: Any) -> str:
    """The same return as a CSV fact table, as a person would hand it to the command line."""
    lines = ["table,sheet,row,column,value"]
    for table, sheet, _key, row, column, value, _decimals in corporate_facts(**differences):
        lines.append(f"{table},{sheet},{row},{column},{value}")
    return "\n".join(lines) + "\n"
