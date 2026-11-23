"""
Small returns for comparison tests, in real PRA001 cells.

Three shapes, because a comparison takes a different path through each:

- ``corporate_return`` — a sheet of a table with a fixed sheet axis (OF 07.00,
  corporates).
- ``own_funds_return`` — a table with no sheets at all (OF 02.00).
- ``geographical_return`` — a table with an OPEN axis (OF 09.01, one sheet per
  country), at any number of countries.

The corporates return is OF 07.00, the corporates sheet (0008): one 1,000,000
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

The own funds return is one figure in the four cells the Bank ties together:
total risk exposure amount = credit risk = standardised approach (boe_b1092,
boe_b1093), and credit risk again in column 0020 (boe_b0716).

The geographical return gives each country three exposure classes and their
total (boe_b0730), in three columns, and an all-countries sheet that is the sum
of the countries cell by cell (boe_b0904), so the return as built breaks no
rule. Its open keys are member LOCAL names (``FR``), the form the rule engine
addresses a cell by. ``restated`` adds an amount to one class in one country
and carries it into both totals, so every rule still holds; ``overlaid`` adds
an amount to a country's total alone, so that country no longer adds up.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

import polars as pl

from pack_builders import VALID_LEI
from rwa_filer.model import CanonicalReturn, ReturnHeader
from rwa_filer.release import resolve_release

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

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

#: Own funds requirements: a table with no sheet axis and no open axis.
OWN_FUNDS_TABLE = "OF02.00.01.01"
#: (row, column) of the cells that carry the one figure.
OWN_FUNDS_CELLS = (("0010", "0010"), ("0040", "0010"), ("0040", "0020"), ("0050", "0010"))

#: Geographical breakdown of SA exposures: one sheet per country, on an open axis.
GEO_TABLE = "OF09.01.01.01"
#: The open-axis member that is every country together.
ALL_COUNTRIES = "x1"
COUNTRIES = ("DE", "FR", "GB")
INSTITUTIONS, CORPORATE, RETAIL, GEO_TOTAL = "0060", "0070", "0080", "0170"
#: Each class's exposure in the first country; the n-th country reports n times as much.
GEO_CLASSES = {INSTITUTIONS: 600_000.0, CORPORATE: 1_000_000.0, RETAIL: 400_000.0}
#: Original exposure, exposure value and RWEA, as a share of the exposure.
GEO_COLUMNS = {"0010": 1.0, "0075": 1.0, "0090": 0.5}
#: ``restated`` for a move with a tie: in every country and column, two classes
#: up by the same amount and the third down by both. Either of the two could be
#: called the row the figure moved to.
TIED_MOVE = {
    (country, row, column): amount
    for country in COUNTRIES
    for column in GEO_COLUMNS
    for row, amount in ((INSTITUTIONS, 10_000.0), (CORPORATE, 10_000.0), (RETAIL, -20_000.0))
}


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


def own_funds_facts(amount: float = 1_000_000.0) -> list[tuple[object, ...]]:
    """The fact rows of one own funds return: ``amount`` in each of ``OWN_FUNDS_CELLS``."""
    return [
        (OWN_FUNDS_TABLE, None, None, row, column, amount, None) for row, column in OWN_FUNDS_CELLS
    ]


def own_funds_return(amount: float = 1_000_000.0) -> CanonicalReturn:
    """One own funds return, in a table that has no sheets."""
    frame = pl.DataFrame(own_funds_facts(amount), schema=COLUMNS, orient="row")
    return CanonicalReturn.from_frame(HEADER, frame)


def own_funds_csv(amount: float = 1_000_000.0) -> str:
    """The own funds return as a CSV fact table: no ``sheet`` column, as the table has none."""
    lines = ["table,row,column,value"]
    for table, _sheet, _key, row, column, value, _decimals in own_funds_facts(amount):
        lines.append(f"{table},{row},{column},{value}")
    return "\n".join(lines) + "\n"


def country_codes(count: int) -> tuple[str, ...]:
    """The first ``count`` countries of the taxonomy's own axis, as member local names."""
    axis = resolve_release(HEADER.module).pack.tables[GEO_TABLE].open_axis
    assert axis is not None, f"{GEO_TABLE} has no open axis"
    names = [member.rpartition(":")[2] for member in axis.members]
    found = tuple(name for name in names if name != ALL_COUNTRIES)[:count]
    assert len(found) == count, f"{GEO_TABLE} has only {len(found)} countries, {count} asked for"
    return found


def geographical_facts(
    countries: Sequence[str] = COUNTRIES,
    *,
    restated: Mapping[tuple[str, str, str], float] | None = None,
    overlaid: Mapping[tuple[str, str], float] | None = None,
    decimals: int | None | Mapping[str, int | None] = None,
) -> list[tuple[object, ...]]:
    """The fact rows of one geographical return.

    Args:
        countries: The open keys to report, besides the all-countries sheet.
        restated: ``{(country, class row, column): amount}`` added to that
            figure and carried into the country's total and both all-countries
            figures: the return still satisfies every rule.
        overlaid: ``{(country, column): amount}`` added to the country's total
            row only (and to the all-countries total, which stays the sum of
            the countries): the total no longer equals its classes.
        decimals: The stated accuracy of every fact, or of each open key's
            facts (``ALL_COUNTRIES`` for the all-countries sheet).
    """
    restated, overlaid = restated or {}, overlaid or {}
    unknown = {key[0] for key in (*restated, *overlaid)} - set(countries)
    assert not unknown, f"{sorted(unknown)} are not among the countries reported"
    figures: dict[tuple[str, str, str], float] = {}
    for position, country in enumerate(countries, start=1):
        for column, share in GEO_COLUMNS.items():
            total = overlaid.get((country, column), 0.0)
            for row, exposure in GEO_CLASSES.items():
                figure = position * exposure * share + restated.get((country, row, column), 0.0)
                figures[(country, row, column)] = figure
                total += figure
            figures[(country, GEO_TOTAL, column)] = total
    together: dict[tuple[str, str, str], float] = {}
    for (_country, row, column), figure in figures.items():
        cell = (ALL_COUNTRIES, row, column)
        together[cell] = together.get(cell, 0.0) + figure

    def accuracy(key: str) -> int | None:
        return decimals if decimals is None or isinstance(decimals, int) else decimals.get(key)

    return [
        (GEO_TABLE, None, key, row, column, figure, accuracy(key))
        for (key, row, column), figure in {**figures, **together}.items()
    ]


def geographical_return(
    countries: Sequence[str] = COUNTRIES, **differences: Any
) -> CanonicalReturn:
    """One geographical return; ``differences`` as ``geographical_facts`` takes them."""
    frame = pl.DataFrame(
        geographical_facts(countries, **differences),
        schema={**dict.fromkeys(COLUMNS[:5], pl.String), "value": pl.Float64, "decimals": pl.Int32},
        orient="row",
    )
    return CanonicalReturn.from_frame(HEADER, frame)


def geographical_csv(countries: Sequence[str] = COUNTRIES, **differences: Any) -> str:
    """The geographical return as a CSV fact table, keyed by ``open_key``."""
    lines = ["table,open_key,row,column,value"]
    for table, _sheet, key, row, column, value, _decimals in geographical_facts(
        countries, **differences
    ):
        lines.append(f"{table},{key},{row},{column},{value}")
    return "\n".join(lines) + "\n"
