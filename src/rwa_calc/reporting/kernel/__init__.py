"""
Shared reporting kernel — helpers common to the COREP and Pillar 3 generators.

Pipeline position:
    OutputAggregator -> {COREPGenerator, Pillar3Generator} -> Excel
    (both generators import their column/filter/sum primitives from here)

Key responsibilities:
- Column discovery and candidate-name resolution (``columns``)
- Approach and balance-sheet-side row filters (``filters``)
- Null-safe column summation primitives (``sums``)
- Template row-dict construction (``rows``)
- Excel sheet writing with a readable-name header band (``excel``)

Why: the COREP and Pillar 3 generators originally each carried a private
copy of these helpers. The copies drifted (see ``filters.filter_on_bs`` for
the documented missing-column divergence), so the shared layer now lives
here with one implementation and one recorded decision per former drift.

References:
- Regulation (EU) 2021/451, Annex I/II (COREP templates)
- CRR Part 8 (Pillar 3 disclosure templates)
- PRA PS1/26 (Basel 3.1 reporting amendments)
"""

from __future__ import annotations

from rwa_calc.reporting.kernel.columns import available_columns, pick
from rwa_calc.reporting.kernel.excel import (
    column_name_map,
    sanitise_sheet_name,
    write_metadata_sheet,
    write_template_sheet,
)
from rwa_calc.reporting.kernel.filters import (
    filter_by_approach,
    filter_off_bs,
    filter_on_bs,
)
from rwa_calc.reporting.kernel.rows import null_row
from rwa_calc.reporting.kernel.sums import col_sum, safe_sum, safe_sum_or_none

__all__ = [
    "available_columns",
    "col_sum",
    "column_name_map",
    "filter_by_approach",
    "filter_off_bs",
    "filter_on_bs",
    "null_row",
    "pick",
    "safe_sum",
    "safe_sum_or_none",
    "sanitise_sheet_name",
    "write_metadata_sheet",
    "write_template_sheet",
]
