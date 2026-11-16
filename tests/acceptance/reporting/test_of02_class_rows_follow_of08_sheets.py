"""
OF 02.00 IRB class rows follow their OF 08.01 sheets - through the gateway engine.

Pipeline position:
    registered Basel 3.1 portfolio (``RUNS``) -> PipelineOrchestrator
        -> COREPGenerator -> filing.build_canonical_return
        -> rwa_filer validate_return (the gateway engine, ``rwa_filer.boe``)

Fourteen OF 02.00 IRB class rows are one data point with an OF 08.01 class
sheet's total (r0010 c0260 / c0276). OF 02.00 used to write 0.0 in every one,
legs or none, so a return whose book had F-IRB non-SME corporates and no A-IRB
ones filed sheet 0012 from OF 08 and, through OF 02.00 row 0356, a phantom
sheet 0011 holding zero. ``boe_b1055`` (ERROR) compares the OF 09.02 country
total with each of those sheets in turn, and the zero sheet failed it: FAIL
[1 satisfied, 1 unsatisfied] on the five portfolios below, Arelle-confirmed on
``art199``. With the row left empty only sheet 0012 is evaluated.

The Bank of England XBRL Filing Manual v1.0.1, rule 2.19, is the authority for
leaving it empty: "inapplicable facts MAY be omitted", "uninteresting zeros"
SHOULD NOT be reported, and a missing numeric fact of a reported template is
treated as zero by the recipient.

``boe_b1041`` pins the zero that must STAY: it is always executed and demands
at least one OF 08.01 row-0080 (slotting) fact on sheet 0002 or 0010, so a book
with no slotting satisfies it only through the zero-filled slotting row of the
FIRB-and-slotting Total that ``c08_sheets.py`` writes.

References:
- Bank of England XBRL Filing Manual v1.0.1 (30 May 2024), rule 2.19
- PRA001 rules ``boe_b1055`` and ``boe_b1041`` (taxonomy v4.1.1)
- tests/unit/reporting/corep/test_c02_00_class_rows_follow_sheets.py
"""

from __future__ import annotations

from datetime import date
from functools import cache
from typing import TYPE_CHECKING

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import RUNS

from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    FILING_TAXONOMY,
    build_canonical_return,
)
from rwa_filer.boe.engine import STATUS_PASS
from rwa_filer.model import ReturnHeader
from rwa_filer.release import resolve_release
from rwa_filer.validate.returns import validate_return

if TYPE_CHECKING:
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.taxonomy.pack import TaxonomyPack

HEADER = ReturnHeader("5493001KJTIIGC8Y1R12", date(2027, 3, 31), FILING_MODULE)
OF08_TABLE = "OF08.01.01.01"

#: Registered Basel 3.1 runs whose only non-SME corporate exposures are F-IRB:
#: sheet 0012 has legs, sheet 0011 none.
ONE_SHEET_PORTFOLIOS = (
    "rich",
    "irb-classes",
    "art199",
    "facility-share-binding",
    "facility-share-nonbinding",
)


@cache
def _canonical(portfolio: str) -> CanonicalReturn:
    """The canonical return of one registered Basel 3.1 portfolio, filed as
    ``export_filing_package`` files it (with the run's own floor summary)."""
    (run,) = [r for r in RUNS if r.framework == "BASEL_3_1" and r.portfolio == portfolio]
    result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=run.framework,
        output_floor_summary=result.output_floor_summary,
    )
    return build_canonical_return(corep, HEADER, pack=_pack()).canonical


@cache
def _pack() -> TaxonomyPack:
    return resolve_release(FILING_MODULE, FILING_TAXONOMY).pack


def _outcome(canonical: CanonicalReturn, rule_id: str) -> tuple[str, int, int]:
    validation = validate_return(canonical, _pack())
    assert validation.report is not None, "no rule book is packaged for PRA001"
    (outcome,) = [r for r in validation.report.results if r.rule_id == rule_id]
    return outcome.status, outcome.satisfied, outcome.unsatisfied


@pytest.mark.parametrize("portfolio", ONE_SHEET_PORTFOLIOS)
def test_boe_b1055_holds_where_only_one_non_sme_corporate_sheet_has_exposures(
    portfolio: str,
) -> None:
    # Arrange
    canonical = _canonical(portfolio)
    facts = canonical.facts
    of08_sheets = set(facts.filter(pl.col("table") == OF08_TABLE)["sheet"].to_list())
    country_total = facts.filter(
        (pl.col("table") == "OF09.02.01.01")
        & (pl.col("row") == "0055")
        & (pl.col("column") == "0110")
        & (pl.col("open_key") == "x1")
    )
    # Adequacy: the rule has both operands, and exactly one of its two sheets is
    # reported by OF 08 - else this portfolio cannot show the phantom sheet.
    assert country_total.height == 1, "OF 09.02 r0055 c0110 (all countries) is not reported"
    assert "0012" in of08_sheets, "OF 08 reports no F-IRB non-SME corporate sheet"
    assert "0011" not in of08_sheets, "the book has A-IRB non-SME corporates"

    # Act
    outcome = _outcome(canonical, "boe_b1055")

    # Assert
    assert outcome == (STATUS_PASS, 1, 0)


def test_boe_b1041_holds_on_a_book_with_no_slotting() -> None:
    """The slotting row stays a reported zero on the FIRB-and-slotting Total: on a
    book with no slotting that zero is the only row-0080 fact ``boe_b1041`` finds."""
    # Arrange
    canonical = _canonical("art199")
    of08 = canonical.facts.filter(pl.col("table") == OF08_TABLE)
    # Adequacy: no slotting and no F-IRB specialised lending, so OF 08 reports no
    # sheet 0010 and a row-0080 fact can come only from the Total (sheet 0002).
    assert "0002" in of08["sheet"].to_list(), "OF 08 reports no FIRB-and-slotting Total"
    assert "0010" not in of08["sheet"].to_list(), "the book has specialised lending"

    # Act
    status, _satisfied, unsatisfied = _outcome(canonical, "boe_b1041")

    # Assert
    assert (status, unsatisfied) == (STATUS_PASS, 0)
    slotting_row = of08.filter(pl.col("row") == "0080")
    assert set(slotting_row["sheet"].to_list()) == {"0002"}
    assert set(slotting_row["value"].to_list()) == {0.0}
