"""
The Basel 3.1 OF 09.02 row and column axes against the ones the Bank publishes.

Why this file exists: the OF 09.02 layout was written as the CRR C 09.02 layout
with Basel 3.1's changes applied, and it kept the CRR row 0010 "Central banks and
central governments" (CRR Annex II C 09.02, point (a) of Article 147(2)). The
PRA's template has no such row. PS1/26 Annex II §3.4.2 begins the OF 09.02 row
instructions at 0020 "Institutions" and defines row 0150 as "the sum of rows 0020,
0030 and 0060" (the Bank's ``boe_b0786``, ERROR) — Art. 147A(1)(a) makes every
central-government, central-bank and quasi-sovereign exposure Standardised, so the
IRB geographical breakdown has nothing to report there. The test that guarded the
layout counted its rows (19) from the layout itself, so it passed with the extra
row in place (`.claude/LESSONS.md` B3).

The source of truth here is the PRA001 taxonomy pack, compiled from the Bank's own
data point model, which our generators and tests cannot drift with: the layout's
row refs and column refs are the published ones of ``OF09.02.01.01``, every one of
them, in published order. CRR C 09.02 keeps its row 0010 — CRR Annex II has it —
and is not measured here: the pack is the PRA001 (Basel 3.1) module only.

References:
- PRA PS1/26 Annex II §3.4.2, OF 09.02 rows 0020-0150 (pp.143-145 of
  ``ps1-26-annex-ii-reporting-instructions.pdf``)
- PRA PS1/26 Art. 147(3), Art. 147A(1)(a) (quasi-sovereigns are Standardised only)
- CRR Annex II C 09.02 row 0010 (point (a) of Article 147(2)), CRR only
- Bank of England Banking Taxonomy v4.1.1, module PRA001, table ``OF09.02.01.01``;
  validation rule ``boe_b0786``
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from rwa_calc.reporting.corep.templates import get_c09_02_columns, get_c09_02_rows
from rwa_calc.reporting.filing.canonical import FILING_MODULE, FILING_TAXONOMY
from rwa_filer.release import resolve_release

if TYPE_CHECKING:
    from rwa_filer.taxonomy.pack import Table

FRAMEWORK = "BASEL_3_1"
TABLE = "OF09.02.01.01"


@pytest.fixture(scope="module")
def table() -> Table:
    return resolve_release(FILING_MODULE, FILING_TAXONOMY).pack.table(TABLE)


def test_the_layout_rows_are_the_published_rows_in_published_order(table: Table) -> None:
    # Arrange
    published = [ref for ref, _label in table.rows]

    # Act
    layout = [row.ref for row in get_c09_02_rows(FRAMEWORK)]

    # Assert
    assert layout == published


def test_the_layout_columns_are_the_published_columns_in_published_order(table: Table) -> None:
    # Arrange
    published = [ref for ref, _label in table.columns]

    # Act
    layout = [column.ref for column in get_c09_02_columns(FRAMEWORK)]

    # Assert
    assert layout == published
