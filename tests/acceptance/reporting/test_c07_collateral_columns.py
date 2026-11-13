"""
C 07.00 / OF 07.00 columns 0130 and 0140 — the comprehensive-method collateral,
capped at the exposure it secures and absent under the Simple Method.

Pipeline position:
    reporting portfolios -> PipelineOrchestrator -> COREPGenerator -> C 07.00 / OF 07.00

Two reporting defects, both template-only: the engine's exposure values and
risk-weighted amounts are right and do not move.

1. COLUMN 0130 WAS NOT CAPPED AT THE EXPOSURE IT SECURES. The engine floors
   each SA exposure at zero after its own collateral (Art. 223(5): E* =
   max{0, ...}), so collateral larger than its loan is simply unused. The
   template summed the whole collateral carrier into column 0130 and floored
   only the CELL, so one loan's unused collateral came off every other loan on
   the sheet: column 0150 below column 0200 in BOTH regimes (``boe_b0471`` /
   ``boe_b0556`` under Basel 3.1, ``v0308_m`` / ``v8726_m`` under CRR).

   The reading taken: column 0130 is each exposure's Cvam CAPPED at the
   volatility-adjusted exposure it secures, and column 0140 is the joint
   volatility and maturity adjustment AS CALCULATED. Annex II's column 0130
   instruction gives only the Cvam formula; the block heading over columns
   0050-0100 says "Collateral that has an effect on the exposure value ...
   shall be capped at the exposure value"; the live ERROR rules ``boe_b0699`` /
   ``v0307_m`` ({c0150} = {c0110} + {c0120} + {c0130}) admit no other reading
   once column 0150 is the per-exposure E*; and EBA Q&A 2015_2010 answers the
   exact case for C 07.00: column 0150 "shall be floored to zero", column 0130
   "reported as calculated ... however capped at the volatility adjusted value
   EVA ... in line with validation rule v0307_m", column 0140 left at its
   calculated value (its worked example moves c130 from -110 to -105 and keeps
   c140 at -10).

2. UNDER THE SIMPLE METHOD COLUMN 0140 REPORTED THE WHOLE MARKET VALUE. For an
   SA row the engine zeroes ``collateral_adjusted_value`` (Art. 222 does not
   reduce the exposure value) but keeps ``collateral_market_value``, and
   column 0140 was market less adjusted — so the entire collateral appeared as
   a "volatility and maturity adjustment" under a column 0130 of zero
   (``boe_b0555``: {c0130} <= {c0140}). Annex II: columns 0120-0140 "shall be
   reported for exposures subject to the Financial Collateral Comprehensive
   Method", and Q&A 2015_2010 puts Simple-Method collateral in columns 050-100.
   This is one of the six Basel 3.1 breaks the deliberately unregistered ``fcsm``
   portfolio exposes (P1.347); no enforced CRR rule sees it (``v0008_h`` is
   deactivated), so it is asserted here directly.

Every assertion runs on real pipeline output, per regime (LESSONS C7: one red
across a parametrisation proves one regime, not two).

References:
- CRR / PS1/26 Art. 222, Art. 223(2)-(5), Art. 239(2)
- COREP Annex II / PS1/26 Annex II, C 07.00 / OF 07.00 columns 0050-0100
  (block heading), 0130, 0140, 0150, 0200
- EBA Q&A 2015_2010; validation rules boe_b0471, boe_b0555, boe_b0556,
  boe_b0699, v0307_m, v0308_m, v8726_m
"""

from __future__ import annotations

from datetime import date
from functools import cache

import polars as pl
import pytest
from tests.fixtures import reporting_over_collateralised_portfolio as oc
from tests.fixtures.reporting_funded_protection_portfolio import build_reporting_fcsm_bundle
from tests.fixtures.reporting_netting_portfolio import build_reporting_netting_bundle

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.domain.enums import CRMCollateralMethod, PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator

_FRAMEWORK: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}
_REGIMES: tuple[str, ...] = tuple(_FRAMEWORK)
_REPORTING_DATE: dict[str, date] = {"crr": date(2025, 12, 31), "b31": date(2027, 6, 1)}

#: (1 - CCF) per off-balance-sheet bucket column, per regime — the published
#: ``boe_b0471`` (Basel 3.1) and ``v0308_m`` (CRR, whose 0160 is the 0% bucket).
_CONVERTED_AWAY: dict[str, dict[str, float]] = {
    "b31": {"0160": 0.9, "0170": 0.8, "0171": 0.6, "0180": 0.5},
    "crr": {"0160": 1.0, "0170": 0.8, "0180": 0.5},
}

_ABS_TOLERANCE: float = 0.005  # half a penny on figures of millions

_BUILDERS = {
    "over-collateralised": oc.build_over_collateralised_bundle,
    "fcsm": lambda _reporting_date: build_reporting_fcsm_bundle(),
    "netting": lambda _reporting_date: build_reporting_netting_bundle(),
}


@cache
def _run(
    portfolio: str, regime: str, method: CRMCollateralMethod
) -> tuple[pl.DataFrame, dict[str, pl.DataFrame]]:
    """One portfolio through one regime and CRM election: (sealed ledger, C 07.00 sheets)."""
    reporting_date = _REPORTING_DATE[regime]
    factory = CalculationConfig.crr if regime == "crr" else CalculationConfig.basel_3_1
    config = factory(
        reporting_date=reporting_date,
        permission_mode=PermissionMode.STANDARDISED,
        crm_collateral_method=method,
    )
    bundle: RawDataBundle = _BUILDERS[portfolio](reporting_date)
    result = PipelineOrchestrator().run_with_data(bundle, config)
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=_FRAMEWORK[regime],
        output_floor_summary=result.output_floor_summary,
    )
    assert corep.c07_00, f"{portfolio}/{regime}: no C 07.00 sheet was emitted at all"
    return result.results.collect(), corep.c07_00


def _comprehensive(portfolio: str, regime: str) -> tuple[pl.DataFrame, dict[str, pl.DataFrame]]:
    return _run(portfolio, regime, CRMCollateralMethod.COMPREHENSIVE)


def _simple(portfolio: str, regime: str) -> tuple[pl.DataFrame, dict[str, pl.DataFrame]]:
    return _run(portfolio, regime, CRMCollateralMethod.SIMPLE)


def _cell(sheet: pl.DataFrame, row_ref: str, col: str) -> float | None:
    row = sheet.filter(pl.col("row_ref") == row_ref)
    return None if row.height == 0 or col not in sheet.columns else row[col][0]


def _rows_reporting(sheets: dict[str, pl.DataFrame], *cols: str) -> list[tuple[str, dict]]:
    """Every (sheet, row) on which all of ``cols`` are reported."""
    return [
        (f"{name} r{row['row_ref']}", row)
        for name, sheet in sheets.items()
        for row in sheet.iter_rows(named=True)
        if all(row.get(col) is not None for col in cols)
    ]


# =============================================================================
# 1. Column 0130 is capped at the exposure each pledge secures
# =============================================================================


@pytest.mark.parametrize("regime", _REGIMES)
def test_the_fully_adjusted_value_ties_to_the_exposure_value(regime: str) -> None:
    """``boe_b0471`` / ``v0308_m`` and ``boe_b0556`` / ``v8726_m``, every row of every sheet.

        {c0200} = {c0150} - sum((1 - CCF_bucket) x {c bucket})
        {c0200} <= {c0150}

    Before the fix both failed on the corporate and total sheets by the 484,210.53
    (CRR) / 284,210.53 (Basel 3.1) of collateral the over-collateralised loans do
    not need.

    Arrange: the over-collateralised portfolio — loans whose collateral exceeds
             them beside a loan whose collateral does not.
    Act:     generate C 07.00 / OF 07.00 under ``regime``.
    Assert:  no breach on any row reporting both columns.
    """
    # Arrange + Act
    ledger, sheets = _comprehensive("over-collateralised", regime)

    # Assert — adequacy first (LESSONS C11): the book really is over-collateralised
    # on some rows and not on others, or the identity below would hold either way.
    by_ref = {row["exposure_reference"]: row for row in ledger.iter_rows(named=True)}
    over = [
        ref
        for ref in oc.OVER_COLLATERALISED
        if by_ref[ref]["collateral_adjusted_value"] > oc.DRAWN[ref]
    ]
    assert over == list(oc.OVER_COLLATERALISED), "no loan's collateral exceeds it"
    assert 0.0 < by_ref[oc.LN_B]["collateral_adjusted_value"] < oc.DRAWN[oc.LN_B], (
        "the surviving leg must carry collateral below its exposure"
    )

    rows = _rows_reporting(sheets, "0150", "0200")
    assert rows, f"{regime}: no row reports both c0150 and c0200 - the identity ran on nothing"
    breaches = []
    for where, row in rows:
        converted_away = sum(w * (row.get(c) or 0.0) for c, w in _CONVERTED_AWAY[regime].items())
        if abs(row["0200"] - (row["0150"] - converted_away)) > _ABS_TOLERANCE:
            breaches.append(
                f"{where}: c0200 {row['0200']:,.2f} != c0150 {row['0150']:,.2f} - {converted_away:,.2f}"
            )
        if row["0200"] > row["0150"] + _ABS_TOLERANCE:
            breaches.append(f"{where}: c0200 {row['0200']:,.2f} > c0150 {row['0150']:,.2f}")
    assert breaches == [], "\n".join(breaches)


@pytest.mark.parametrize("regime", _REGIMES)
def test_the_fully_adjusted_value_is_the_waterfall_without_a_floor(regime: str) -> None:
    """``boe_b0699`` / ``v0307_m``: {c0150} = {c0110} + {c0120} + {c0130}, signed.

    Column 0150 is E*, floored at zero PER EXPOSURE (Art. 223(5)). With column
    0130 capped per exposure the identity holds on the published cells; the
    cell-level ``max(0, ...)`` it used to lean on can never bind.

    Green before the fix too, by construction — the defect was a column 0150
    that agreed with column 0130 and disagreed with column 0200. What this test
    rejects is the OTHER reading of the column 0130 instruction: reporting Cvam
    uncapped while flooring column 0150 per exposure breaks it by the unused
    collateral (1,800,000 - 984,210.53 against 1,300,000 under CRR).

    Arrange: the over-collateralised portfolio.
    Act:     generate C 07.00 / OF 07.00 under ``regime``.
    Assert:  the identity holds on every row reporting 0110, 0130 and 0150.
    """
    # Arrange + Act
    _ledger, sheets = _comprehensive("over-collateralised", regime)

    # Assert
    rows = _rows_reporting(sheets, "0110", "0130", "0150")
    assert rows, f"{regime}: no row reports 0110, 0130 and 0150"
    breaches = [
        f"{where}: c0150 {row['0150']:,.2f} != {row['0110']:,.2f} + {row.get('0120') or 0.0:,.2f} "
        f"+ {row['0130']:,.2f}"
        for where, row in rows
        if abs(row["0150"] - (row["0110"] + (row.get("0120") or 0.0) + row["0130"]))
        > _ABS_TOLERANCE
    ]
    assert breaches == [], "\n".join(breaches)


@pytest.mark.parametrize("sheet_key", ["corporate", "total"])
@pytest.mark.parametrize("regime", _REGIMES)
def test_column_0130_is_each_loans_collateral_no_more_than_it_owes(
    regime: str, sheet_key: str
) -> None:
    """The waterfall of the over-collateralised book, cell by cell.

    Before the fix (the module docstring of the fixture): CRR 0130 -984,210.53,
    0150 815,789.47; Basel 3.1 0130 -684,210.53, 0150 1,015,789.47.

    Arrange: the over-collateralised portfolio.
    Act:     generate C 07.00 / OF 07.00 under ``regime``.
    Assert:  0130 = -(each loan's Cvam capped at what it owes) — 500,000 under
             CRR, where the netted deposit is collateral, 400,000 under Basel 3.1,
             where column 0035 carries it; 0150 = 0200 = 1,300,000. The OC-B
             pledge's 200,000 is in that figure untouched, so a fix that zeroed
             the column fails here.
    """
    # Arrange
    deposit_in_0130 = regime == "crr"

    # Act
    _ledger, sheets = _comprehensive("over-collateralised", regime)

    # Assert
    sheet = sheets[sheet_key]
    assert _cell(sheet, "0010", "0130") == pytest.approx(
        -oc.capped_collateral(deposit_in_column_0130=deposit_in_0130)
    )
    assert _cell(sheet, "0010", "0150") == pytest.approx(oc.TOTAL_EXPOSURE_VALUE)
    assert _cell(sheet, "0010", "0200") == pytest.approx(oc.TOTAL_EXPOSURE_VALUE)


@pytest.mark.parametrize("regime", _REGIMES)
def test_column_0140_keeps_the_adjustment_as_calculated(regime: str) -> None:
    """Column 0140 is the joint adjustment C - Cvam as CALCULATED, not scaled by the cap.

    The reading of EBA Q&A 2015_2010 (c130 capped from -110 to -105, c140 left
    at -10). The OC-C pledge pins it: Cvam 184,210.53 is capped to the 100,000
    the loan owes, and its adjustment stays 315,789.47 — a cap that scaled the
    pledge down pro rata would report 171,428.57.

    Arrange: the over-collateralised portfolio.
    Act:     generate C 07.00 / OF 07.00 under ``regime``.
    Assert:  0140 = -315,789.47 on the corporate total row.
    """
    # Arrange + Act
    _ledger, sheets = _comprehensive("over-collateralised", regime)

    # Assert
    assert _cell(sheets["corporate"], "0010", "0140") == pytest.approx(-oc.VOL_MAT_ADJUSTMENT)


@pytest.mark.parametrize("regime", _REGIMES)
def test_no_exposure_value_or_rwa_moves(regime: str) -> None:
    """The fix is template-only: every leg's engine figures are the hand calculation.

    Green before and after the fix BY DESIGN — it states that the defect was
    never in the engine, so the cap must not be implemented there.

    Arrange: the over-collateralised portfolio.
    Act:     run the pipeline under ``regime``.
    Assert:  each loan's ``ead_final`` and ``rwa_final`` (100% risk weight) are
             max(0, drawn - Cvam).
    """
    # Arrange + Act
    ledger, _sheets = _comprehensive("over-collateralised", regime)

    # Assert
    by_ref = {row["exposure_reference"]: row for row in ledger.iter_rows(named=True)}
    for ref, expected in oc.EXPOSURE_VALUE.items():
        assert by_ref[ref]["ead_final"] == pytest.approx(expected), ref
        assert by_ref[ref]["rwa_final"] == pytest.approx(expected), ref


# =============================================================================
# 2. Under the Simple Method the comprehensive-method columns carry nothing
# =============================================================================

#: (portfolio, regime) pairs whose Simple-Method run put collateral market value
#: into column 0140 before the fix. Basel 3.1 ``netting`` is NOT one: there the
#: only collateral is the netted deposit, which column 0140 already left out.
_SIMPLE_CASES: tuple[tuple[str, str], ...] = (("fcsm", "crr"), ("fcsm", "b31"), ("netting", "crr"))


@pytest.mark.parametrize(("portfolio", "regime"), _SIMPLE_CASES)
def test_simple_method_collateral_is_not_reported_as_a_comprehensive_adjustment(
    portfolio: str, regime: str
) -> None:
    """Columns 0130 and 0140 are zero on every row under the Simple Method.

    Before the fix column 0140 was -1,200,000 on the ``fcsm`` corporate sheet in
    both regimes and -3,000,000 on the CRR ``netting`` one, under a column 0130
    of zero — ``boe_b0555`` broken where it is enforced.

    Arrange: a book electing the Art. 222 Simple Method.
    Act:     generate C 07.00 / OF 07.00 under ``regime``.
    Assert:  column 0070 carries the collateral (the adequacy check), and no row
             reports anything in columns 0130 or 0140.
    """
    # Arrange + Act
    ledger, sheets = _simple(portfolio, regime)

    # Assert — adequacy: the Simple Method recognised collateral that the ledger
    # still carries at market value, so the defect's shape is present.
    assert ledger["collateral_market_value"].fill_null(0.0).sum() > 0.0
    assert (_cell(sheets["corporate"], "0010", "0070") or 0.0) < 0.0, (
        "no Simple-Method collateral in column 0070 - the run did not elect the method"
    )

    rows = _rows_reporting(sheets, "0140")
    assert rows, "no row reports column 0140"
    reported = [
        f"{where}: c0130 {row.get('0130')}, c0140 {row['0140']}"
        for where, row in rows
        if abs(row["0140"]) > _ABS_TOLERANCE or abs(row.get("0130") or 0.0) > _ABS_TOLERANCE
    ]
    assert reported == [], "\n".join(reported)


@pytest.mark.parametrize("regime", _REGIMES)
def test_the_comprehensive_method_keeps_columns_0130_and_0140_on_the_same_book(
    regime: str,
) -> None:
    """The control: the SAME book under the Comprehensive Method reports both columns.

    LESSONS B5's surviving leg for defect 2 — a change that zeroed column 0140
    everywhere would pass the Simple-Method test above and fail here. No pledge
    exceeds its loan, so the cap leaves these figures as they were.

    Arrange: the ``fcsm`` book under the default Comprehensive election.
    Act:     generate C 07.00 / OF 07.00 under ``regime``.
    Assert:  0130 = -1,064,235.50 and 0140 = -135,764.50 on the corporate total
             row — the USD bond's haircut and the cash pledge.
    """
    # Arrange + Act
    _ledger, sheets = _comprehensive("fcsm", regime)

    # Assert
    corporate = sheets["corporate"]
    assert _cell(corporate, "0010", "0130") == pytest.approx(-1_064_235.4980121828)
    assert _cell(corporate, "0010", "0140") == pytest.approx(-135_764.50198781723)
