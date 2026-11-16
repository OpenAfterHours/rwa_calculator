"""
OF 08.01's grey cells and retail maturity on registered Basel 3.1 portfolios, through the gateway.

Pipeline position:
    registered Basel 3.1 portfolio (``RUNS``) -> PipelineOrchestrator
        -> COREPGenerator -> filing.build_canonical_return
        -> rwa_filer trace_return (the gateway engine, ``rwa_filer.boe``)

Two defects, one gate each:

- Grey cells. OF 08.01 computed every column on every active row and reported
  all of it; the PRA001 taxonomy has no data point for 279 of the template's
  row-by-column positions on any sheet, plus seven that depend on the sheet.
  ``build_canonical_return`` could place none of those figures (reason
  ``cell_not_reportable``): 97 on ``irb-classes`` and 131 on ``rich``, zeros
  included, and 60 distinct non-zero figures across the registered portfolios,
  which the filing-mapping ratchet had banked as the state.
- Retail maturity. Column 0250 was filled on retail sheets and averaged into
  the A-IRB Total, against Annex II ("This column shall therefore not be filled
  in for the exposure class 'retail' or for exposures subject to the slotting
  approach", PS1/26 Annex II p.111). The Bank's Error rule ``boe_b0748`` — the
  A-IRB Total equals the sum of the A-IRB sheets, column 0250 among the summed
  columns — then failed on that column alone, on both portfolios: 1,673 on the
  Total against 1,673 + 1,673 on two sheets. With retail left out there is at
  most one A-IRB sheet reporting a maturity on these returns, and the rule
  passes; that the rule SUMS an average is the Bank's and stays latent here
  (no registered return has two non-retail A-IRB sheets).

Column 0254 (Annex II p.112: "shall not be reported for sheets relating to the
FIRB approach or the slotting approach") is checked on ``irb-shapes``, which has
both approaches: no column-0254 fact on any F-IRB or slotting sheet.

References:
- PRA PS1/26 Annex I (OF 08.01); Annex II §3.3.3 columns 0250 (p.111) and 0254
  (p.112)
- Bank of England taxonomy v4.1.1, tables OF08.01.01.01 / .02; rule
  ``boe_b0748``
- tests/contracts/test_of08_published_cells.py (the grid, held to the taxonomy)
"""

from __future__ import annotations

from datetime import date
from functools import cache
from typing import TYPE_CHECKING, NamedTuple

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import RUNS

from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    FILING_TAXONOMY,
    REASON_CELL,
    build_canonical_return,
)
from rwa_filer.boe.engine import STATUS_PASS
from rwa_filer.model import ReturnHeader
from rwa_filer.release import resolve_release
from rwa_filer.validate.returns import trace_return

if TYPE_CHECKING:
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.taxonomy.pack import TaxonomyPack

HEADER = ReturnHeader("5493001KJTIIGC8Y1R12", date(2027, 3, 31), FILING_MODULE)
OF08_TABLE = "OF08.01.01.01"
TOTAL_RULE = "boe_b0748"

#: The published codes of the retail A-IRB sheets and of the F-IRB / slotting
#: sheets (with their Total, 0002).
RETAIL_CODES = ("0015", "0016", "0017", "0018", "0019", "0020", "0021")
FIRB_SLOTTING_CODES = ("0002", "0006", "0010", "0012", "0022", "0024")

#: The two returns ``boe_b0748`` failed on (column 0250), and a third with both
#: F-IRB and slotting sheets for column 0254.
PORTFOLIOS = ("irb-classes", "rich")
BOTH_APPROACHES = "irb-shapes"


class _Filed(NamedTuple):
    """One registered Basel 3.1 portfolio, generated and filed."""

    corep: COREPTemplateBundle
    canonical: CanonicalReturn
    unplaced: pl.DataFrame


@cache
def _filed(portfolio: str) -> _Filed:
    (run,) = [r for r in RUNS if r.framework == "BASEL_3_1" and r.portfolio == portfolio]
    result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=run.framework,
        output_floor_summary=result.output_floor_summary,
    )
    mapping = build_canonical_return(corep, HEADER, pack=_pack())
    return _Filed(corep, mapping.canonical, mapping.unplaced)


@cache
def _pack() -> TaxonomyPack:
    return resolve_release(FILING_MODULE, FILING_TAXONOMY).pack


def _facts(canonical: CanonicalReturn, column: str, codes: tuple[str, ...]) -> pl.DataFrame:
    return canonical.facts.filter(
        (pl.col("table") == OF08_TABLE)
        & (pl.col("column") == column)
        & pl.col("sheet").is_in(codes)
    )


@pytest.mark.parametrize("portfolio", PORTFOLIOS)
def test_no_of08_01_figure_lands_in_a_cell_the_taxonomy_does_not_publish(portfolio: str) -> None:
    # Arrange
    filed = _filed(portfolio)
    assert filed.corep.c08_01, "no OF 08.01 sheet generated: nothing would be placed"

    # Act
    grey = filed.unplaced.filter(
        (pl.col("template") == "c08_01") & (pl.col("reason") == REASON_CELL)
    )

    # Assert
    assert grey.height == 0, grey.head(10)


@pytest.mark.parametrize("portfolio", PORTFOLIOS)
def test_the_airb_total_rule_passes_once_retail_reports_no_maturity(portfolio: str) -> None:
    # Arrange
    filed = _filed(portfolio)
    retail = filed.canonical.facts.filter(
        (pl.col("table") == OF08_TABLE) & pl.col("sheet").is_in(RETAIL_CODES)
    )
    assert retail.height > 0, "no retail A-IRB sheet filed: the maturity rule cannot be exercised"

    # Act
    validation, _trace = trace_return(filed.canonical, _pack())
    assert validation.report is not None, "no rule book for PRA001"
    statuses = {result.rule_id: result.status for result in validation.report.results}

    # Assert
    assert _facts(filed.canonical, "0250", RETAIL_CODES).height == 0
    assert statuses[TOTAL_RULE] == STATUS_PASS


def test_no_firb_or_slotting_sheet_files_an_unrecognised_exposure_adjustment() -> None:
    # Arrange
    filed = _filed(BOTH_APPROACHES)
    firb = filed.canonical.facts.filter(
        (pl.col("table") == OF08_TABLE) & pl.col("sheet").is_in(FIRB_SLOTTING_CODES)
    )
    assert set(firb["sheet"].to_list()) >= {"0002", "0010"}, (
        "the return files no F-IRB-and-slotting sheets: the column cannot be exercised"
    )

    # Act
    filed_0254 = _facts(filed.canonical, "0254", FIRB_SLOTTING_CODES)

    # Assert
    assert filed_0254.height == 0, filed_0254.head(10)
