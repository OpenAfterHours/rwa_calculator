"""
Shared data for the breakdown tests: a detail file of OF 07.00 corporates, one row per part of a cell.

Every exposure is posted to its row of the Corporates sheet (0008) and of the
Total sheet (0001), as a firm's own data would be, in the cells the PRA001
taxonomy accepts there. Four business units, each one consistent on its own,
then three defects planted where a person would have to find them:

- ``Asset Finance`` deducts its 100,000 of collateral twice, so its fully
  adjusted exposure (c0150) is 100,000 short of what its exposure value
  (c0200) was worked from: ``boe_b0471`` (Error) and ``boe_b0556`` break, and
  every gap is exactly 100,000, all of it Asset Finance's.
- Journal ``JNL-1`` adds a 50,000 facility to Commercial Banking on the total
  and on-balance-sheet rows, and on no risk-weight row: ``boe_b0719`` and
  ``boe_b0721`` break by exactly 50,000, all of it Commercial Banking's (and
  JNL-1's, by source).
- Journal ``JNL-2`` moves 5,000 of net exposure (c0040) from Private Banking to
  Corporate & Institutional and nothing else: each unit's own c0040 no longer
  equals its c0010 less its provisions, while the total still does —
  ``boe_b0708`` holds in the return and breaks for both units, a break the
  total hides.

``clean_rows`` is the same book without the defects: nothing breaks, on the
return or on any unit's figures — the case an alarm must stay quiet on.
"""

from __future__ import annotations

import csv
from datetime import date
from functools import cache
from typing import TYPE_CHECKING, Final

import polars as pl

from pack_builders import VALID_LEI
from rwa_filer.readers import HeaderFields
from rwa_filer.release import resolve_release

if TYPE_CHECKING:
    from pathlib import Path

TABLE: Final = "OF07.00.01.01"
CORPORATES: Final = "0008"
TOTAL: Final = "0001"
REFERENCE_DATE: Final = "2027-03-31"
HEADER_FIELDS: Final = HeaderFields(
    entity=VALID_LEI, reference_date=date(2027, 3, 31), module="PRA001"
)
HEADER_FORM: Final = {"entity": VALID_LEI, "reference_date": REFERENCE_DATE, "module": "PRA001"}
HEADER_ARGS: Final = [
    "--entity",
    VALID_LEI,
    "--reference-date",
    REFERENCE_DATE,
    "--module",
    "PRA001",
    "--submission-date",
    "2026-11-22",
    "--no-progress",
]
COLUMNS: Final = ("table", "sheet", "row", "column", "value", "business_unit", "source", "line_id")

#: The planted defects' amounts.
DOUBLED_COLLATERAL: Final = 100_000.0
LATE_FACILITY: Final = 50_000.0
MOVED_PROVISION: Final = 5_000.0

ASSET_FINANCE: Final = "Asset Finance"
COMMERCIAL: Final = "Commercial Banking"
CORPORATE: Final = "Corporate & Institutional"
PRIVATE: Final = "Private Banking"

#: (unit, source, original exposure, provisions, collateral), each at 100%, unrated.
_EXPOSURES: Final = (
    (COMMERCIAL, "LENDING", 1_000_000.0, 10_000.0, 0.0),
    (ASSET_FINANCE, "LEASING", 500_000.0, 0.0, DOUBLED_COLLATERAL),
    (CORPORATE, "LENDING", 300_000.0, 3_000.0, 0.0),
    (PRIVATE, "LENDING", 200_000.0, 2_000.0, 0.0),
)
_RISK_WEIGHT_ROW: Final = "0230"


def detail_rows(*, defects: bool = True) -> list[dict[str, object]]:
    """The detail file's rows: each unit's exposure, then the journals."""
    rows: list[dict[str, object]] = []
    for unit, source, original, provisions, collateral in _EXPOSURES:
        doubled = defects and unit == ASSET_FINANCE
        _post(rows, unit, source, _exposure(original, provisions, collateral, doubled=doubled))
    if defects:
        late = _exposure(LATE_FACILITY, 0.0, 0.0, doubled=False)
        _post(rows, COMMERCIAL, "JNL-1", late, risk_weight_row=False)
        for unit, sign in ((CORPORATE, 1.0), (PRIVATE, -1.0)):
            _post(rows, unit, "JNL-2", {"0040": sign * MOVED_PROVISION}, risk_weight_row=False)
    for number, row in enumerate(rows, start=1):
        row["line_id"] = f"L{number:04d}"
    return rows


def clean_rows() -> list[dict[str, object]]:
    """The same book without the defects: every unit consistent, nothing broken."""
    return detail_rows(defects=False)


def write_detail(path: Path, rows: list[dict[str, object]] | None = None) -> Path:
    """Write ``rows`` (default: the book with its defects) as a CSV detail file."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(detail_rows() if rows is None else rows)
    return path


def summed(rows: list[dict[str, object]]) -> pl.DataFrame:
    """The return ``rows`` sum to, cell by cell, worked out independently of the reader."""
    frame = pl.DataFrame(rows).select("table", "sheet", "row", "column", "value")
    return frame.group_by("table", "sheet", "row", "column").agg(pl.col("value").sum())


# =============================================================================
# Private helpers
# =============================================================================


def _exposure(
    original: float, provisions: float, collateral: float, *, doubled: bool
) -> dict[str, float]:
    """One on-balance-sheet exposure's columns, consistent unless ``doubled``."""
    net = original - provisions
    deducted = collateral * (2 if doubled else 1)
    value = net - collateral
    return {
        "0010": original,
        "0030": -provisions,
        "0040": net,
        "0110": net,
        "0130": -deducted,
        "0150": net - deducted,
        "0200": value,
        "0220": value,
        "0235": value,
    }


def _post(
    rows: list[dict[str, object]],
    unit: str,
    source: str,
    cells: dict[str, float],
    *,
    risk_weight_row: bool = True,
) -> None:
    """Post ``cells`` to the total row, the on-balance-sheet row and the risk-weight row,
    on the Corporates and the Total sheets, keeping only the cells the taxonomy accepts."""
    accepted = _reportable()
    lines = ("0010", "0070", *((_RISK_WEIGHT_ROW,) if risk_weight_row else ()))
    for sheet in (CORPORATES, TOTAL):
        for row in lines:
            for column, value in cells.items():
                if value == 0 or (sheet, row, column) not in accepted:
                    continue
                rows.append(
                    {
                        "table": TABLE,
                        "sheet": sheet,
                        "row": row,
                        "column": column,
                        "value": value,
                        "business_unit": unit,
                        "source": source,
                    }
                )


@cache
def _reportable() -> frozenset[tuple[str, str, str]]:
    """The (sheet, row, column) cells of OF 07.00 the PRA001 taxonomy accepts."""
    cells = resolve_release("PRA001", None).pack.cells.filter(pl.col("table") == TABLE)
    return frozenset(cells.select("sheet", "row", "column").iter_rows())


GROUP_CSV_HEADER = "table,sheet,row,column,value,text_value,decimals,reporting_unit\n"
GROUP_CSV_ROWS = (
    "C32.01.01.01,,0010,0070,,Group wording,,Group\n"
    "OF07.00.01.01,0008,0010,0010,100,,2,Group\n"
    "OF07.00.01.01,0008,0010,0040,80,,2,Group\n"
)
UNIT_CSV_ROWS = (
    "C32.01.01.01,,0010,0070,,Retail wording,,Retail\n"
    "C32.01.01.01,,0010,0070,,Commercial wording,,Commercial\n"
    "OF07.00.01.01,0008,0010,0010,50,,2,Retail\n"
    "OF07.00.01.01,0008,0010,0040,50,,2,Retail\n"
    "OF07.00.01.01,0008,0010,0010,30,,2,Commercial\n"
    "OF07.00.01.01,0008,0010,0040,20,,2,Commercial\n"
    "OF07.00.01.01,0008,0010,0200,90,,2,Partial\n"
    "OF07.00.01.01,0008,0010,0010,5,,2,Partial\n"
)


def group_files(tmp_path: Path) -> tuple[Path, Path]:
    plain, combined = tmp_path / "group.csv", tmp_path / "combined.csv"
    plain.write_text(GROUP_CSV_HEADER + GROUP_CSV_ROWS)
    combined.write_text(GROUP_CSV_HEADER + UNIT_CSV_ROWS + GROUP_CSV_ROWS)
    return plain, combined
