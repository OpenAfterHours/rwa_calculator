"""
OF 08.01's conversion-factor rows on the registered Basel 3.1 portfolios, through the gateway.

Pipeline position:
    registered Basel 3.1 portfolio (``RUNS``) -> PipelineOrchestrator
        -> COREPGenerator -> filing.build_canonical_return
        -> rwa_filer trace_return (the gateway engine, ``rwa_filer.boe``)

Row 0030 "Off balance sheet items" is broken down by conversion factor in rows
0031 (10%), 0032 (20%), 0001 (40%), 0033 (50%), 0034 (100%) and 0035 (own
estimate) — PS1/26 Annex II p.116. The Basel 3.1 generator left all of them
empty and had no row 0001, so the Bank's Error rules failed wherever an IRB
off-balance-sheet item existed: ``boe_b0741`` (OF08.01.01.02 r0010 c0120 = the
sum of the six rows' c0110) three times on ``irb-shapes`` and twice on
``facility-share-binding``, ``boe_b0742`` (row 0030 = the sum of the six rows,
over 30 columns) 26 and 14 times.

Two registered portfolios hold IRB off-balance-sheet legs: ``irb-shapes`` (an
F-IRB undrawn commitment at 40% and an F-IRB guarantee at 100%, both to one
obligor on sheet 0012, and a slotting guarantee at 100% on sheet 0010) and
``facility-share-binding`` (an F-IRB undrawn share at 50%, sheet 0012).

What stays failing is the Bank's, not ours: ``boe_b0742`` adds rows on column
0250, an exposure-weighted average maturity, and on 0300, a count of obligors —
neither adds across rows (LESSONS C5; publisher issue PI-07a). On ``irb-shapes``
two buckets of sheet 0012 each carry the obligor's maturity, 1,673 days, against
1,673 on row 0030, so column 0250 fails there and on the FIRB-and-slotting Total;
column 0300 is unequal too (1 against 1 + 1) but inside the rule's rounding
allowance for integer facts, so the gateway passes it.

References:
- PRA PS1/26 Annex II §3.3.3 rows 0031-0035 and 0001 (p.116), columns 0250
  (p.111) and 0300 (p.114)
- PRA PS1/26 Art. 111(1) Table A1; Art. 166C(1)
- Bank of England taxonomy v4.1.1 rules ``boe_b0741``, ``boe_b0742``
"""

from __future__ import annotations

from datetime import date
from functools import cache
from typing import TYPE_CHECKING, NamedTuple

import polars as pl
import pytest
from tests.acceptance.reporting.test_supervisory_validations import RUNS
from tests.fixtures.facility_share_portfolio import HEADROOM_SHARE
from tests.fixtures.reporting_irb_shapes_portfolio import (
    DRAWN_CORP_ONB,
    LIMIT_CORP_OC,
    NOMINAL_CORP_GTEE,
    NOMINAL_SL,
)

from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.c08_sheets import c08_class_sheets
from rwa_calc.reporting.corep.ccf_buckets import OF08_01_CCF_ROWS
from rwa_calc.reporting.corep.generator import COREPGenerator
from rwa_calc.reporting.filing.canonical import (
    FILING_MODULE,
    FILING_TAXONOMY,
    build_canonical_return,
)
from rwa_calc.reporting.filing.sheet_maps import SHEET_INDEX_MAPS
from rwa_filer.model import ReturnHeader
from rwa_filer.release import resolve_release
from rwa_filer.validate.returns import trace_return

if TYPE_CHECKING:
    from rwa_calc.reporting.corep.generator import COREPTemplateBundle
    from rwa_filer.boe.engine import RuleTrace
    from rwa_filer.model import CanonicalReturn
    from rwa_filer.taxonomy.pack import TaxonomyPack

HEADER = ReturnHeader("5493001KJTIIGC8Y1R12", date(2027, 3, 31), FILING_MODULE)
OFF_BS_ROW = "0030"
ROWS_RULE = "boe_b0742"
EXPOSURE_VALUE_RULE = "boe_b0741"

#: The F-IRB corporate undrawn commitment's headroom, at the Table A1 40%.
CORPORATE_UNDRAWN = LIMIT_CORP_OC - DRAWN_CORP_ONB
CORPORATE_UNDRAWN_CCF = 0.40

IRB_SHAPES = "irb-shapes"
FACILITY_SHARE = "facility-share-binding"

#: The only places ``boe_b0742`` stays unsatisfied: (column, published sheet).
#: Column 0250 on sheet 0012 and on the FIRB-and-slotting Total (module
#: docstring). The Bank's rule, not our figures.
RULE_LIMIT = {IRB_SHAPES: {("0250", "0002"), ("0250", "0012")}, FACILITY_SHARE: set()}

B31_PORTFOLIOS = sorted({run.portfolio for run in RUNS if run.framework == "BASEL_3_1"})


class _Filed(NamedTuple):
    corep: COREPTemplateBundle
    canonical: CanonicalReturn


@cache
def _filed(portfolio: str) -> _Filed:
    (run,) = [r for r in RUNS if r.framework == "BASEL_3_1" and r.portfolio == portfolio]
    result = PipelineOrchestrator().run_with_data(run.build_bundle(), run.build_config())
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=run.framework,
        output_floor_summary=result.output_floor_summary,
    )
    return _Filed(corep, build_canonical_return(corep, HEADER, pack=_pack()).canonical)


@cache
def _pack() -> TaxonomyPack:
    return resolve_release(FILING_MODULE, FILING_TAXONOMY).pack


@cache
def _trace(portfolio: str) -> RuleTrace:
    validation, trace = trace_return(_filed(portfolio).canonical, _pack())
    assert validation.report is not None and trace is not None, "no rule book for PRA001"
    return trace


def _sheet(portfolio: str, code: str) -> pl.DataFrame:
    (key,) = SHEET_INDEX_MAPS["of08"][code].bundle_keys
    return _filed(portfolio).corep.c08_01[key]


def _cell(sheet: pl.DataFrame, row: str, column: str) -> float | None:
    matched = sheet.filter(pl.col("row_ref") == row)
    if matched.height == 0:
        return None
    value = matched[column][0]
    return None if value is None else float(value)


def _unsatisfied(portfolio: str, rule_id: str) -> set[tuple[str, ...]]:
    places = [dict(ev.place) for ev in _trace(portfolio).evaluations if ev.rule_id == rule_id]
    failing = [
        dict(ev.place)
        for ev in _trace(portfolio).evaluations
        if ev.rule_id == rule_id and not ev.holds
    ]
    assert places, f"{rule_id} was never evaluated on {portfolio}: nothing would be checked"
    return {tuple(place[axis] for axis in ("c", "z") if axis in place) for place in failing}


@pytest.mark.parametrize(
    ("code", "row", "column", "expected"),
    [
        ("0012", "0001", "0020", CORPORATE_UNDRAWN),
        ("0012", "0001", "0110", CORPORATE_UNDRAWN * CORPORATE_UNDRAWN_CCF),
        ("0012", "0034", "0020", NOMINAL_CORP_GTEE),
        ("0012", "0034", "0110", NOMINAL_CORP_GTEE),
        ("0010", "0034", "0020", NOMINAL_SL),
        ("0002", "0001", "0020", CORPORATE_UNDRAWN),
        ("0002", "0034", "0020", NOMINAL_CORP_GTEE + NOMINAL_SL),
    ],
)
def test_irb_shapes_files_each_off_balance_sheet_item_in_its_conversion_factor_row(
    code: str, row: str, column: str, expected: float
) -> None:
    # Arrange
    sheet = _sheet(IRB_SHAPES, code)

    # Act
    reported = _cell(sheet, row, column)

    # Assert
    assert reported == pytest.approx(expected, rel=1e-12)


def test_irb_shapes_rows_add_up_to_the_off_balance_sheet_exposure_value() -> None:
    """``boe_b0741``'s left side is OF08.01.01.02 r0010 c0120 — row 0030's c0110."""
    # Arrange
    sheet = _sheet(IRB_SHAPES, "0012")

    # Act
    breakdown = sum(_cell(sheet, row, "0110") or 0.0 for row in OF08_01_CCF_ROWS)

    # Assert
    assert _cell(sheet, "0010", "0120") == pytest.approx(breakdown, rel=1e-12)
    assert breakdown == pytest.approx(
        CORPORATE_UNDRAWN * CORPORATE_UNDRAWN_CCF + NOMINAL_CORP_GTEE, rel=1e-12
    )


@pytest.mark.parametrize("code", ["0012", "0002"])
def test_facility_share_files_its_undrawn_share_in_the_50_percent_row(code: str) -> None:
    # Arrange
    sheet = _sheet(FACILITY_SHARE, code)

    # Act
    gross, value = _cell(sheet, "0033", "0020"), _cell(sheet, "0033", "0110")

    # Assert
    assert gross == pytest.approx(HEADROOM_SHARE, rel=1e-12)
    assert value == pytest.approx(_cell(sheet, OFF_BS_ROW, "0110"), rel=1e-12)
    assert value == pytest.approx(HEADROOM_SHARE * 0.5, rel=1e-12)


@pytest.mark.parametrize("portfolio", [IRB_SHAPES, FACILITY_SHARE])
def test_the_exposure_value_rule_holds(portfolio: str) -> None:
    # Arrange / Act
    failing = _unsatisfied(portfolio, EXPOSURE_VALUE_RULE)

    # Assert
    assert failing == set()


@pytest.mark.parametrize("portfolio", [IRB_SHAPES, FACILITY_SHARE])
def test_the_rows_rule_fails_only_where_it_adds_an_average(portfolio: str) -> None:
    # Arrange / Act
    failing = _unsatisfied(portfolio, ROWS_RULE)

    # Assert
    assert failing == RULE_LIMIT[portfolio]


@pytest.mark.parametrize("portfolio", B31_PORTFOLIOS)
def test_no_off_balance_sheet_money_misses_its_conversion_factor_row(portfolio: str) -> None:
    """LESSONS B6 on every registered Basel 3.1 portfolio: the off-balance-sheet
    gross on row 0030 that no bucket row carries, summed over the class sheets."""
    # Arrange
    sheets = c08_class_sheets(_filed(portfolio).corep.c08_01)

    # Act
    missing = sum(
        (_cell(sheet, OFF_BS_ROW, "0020") or 0.0)
        - sum(_cell(sheet, row, "0020") or 0.0 for row in OF08_01_CCF_ROWS)
        for sheet in sheets.values()
    )

    # Assert
    assert missing == pytest.approx(0.0, abs=0.005)


def test_the_conservation_check_sees_off_balance_sheet_money() -> None:
    """Adequacy for the check above: it is not proved by empty rows alone."""
    # Arrange / Act
    gross = {
        portfolio: sum(
            _cell(sheet, OFF_BS_ROW, "0020") or 0.0
            for sheet in c08_class_sheets(_filed(portfolio).corep.c08_01).values()
        )
        for portfolio in (IRB_SHAPES, FACILITY_SHARE)
    }

    # Assert
    assert all(amount > 0 for amount in gross.values()), gross
