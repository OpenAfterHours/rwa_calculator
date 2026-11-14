"""
OF 07.00 deducts on-balance-sheet netting ONCE — the published identity, asserted.

Pipeline position:
    netting portfolios -> PipelineOrchestrator -> COREPGenerator -> C 07.00 / OF 07.00

The defect (escape log, 2026-09-05). On the Basel 3.1 template a netted deposit
was deducted in column 0035 "(-) Adjustment to exposure value due to on-balance
sheet netting", so column 0040 was already net of it, and AGAIN inside column
0130 "(-) Financial collateral adjusted value", because CRR Art. 219 turns the
deposit into synthetic cash collateral and the template summed the whole
``collateral_adjusted_value`` there. Column 0150 (E*) came out below column 0200
(the exposure value, which the engine had netted once and correctly) by the
amount in column 0035.

PS1/26 Annex II settles which column owns the deposit: column 0035 is "the
reduction in exposure value due to on-balance sheet netting determined in
accordance with Article 219", column 0040 is the "sum of columns 0010, 0030, and
0035", and PS1/26 Art. 223(3) starts the Financial Collateral Comprehensive
Method from E = "where Article 219 applies, the exposure value calculated in
accordance with that Article". So the deposit is in column 0035, at the value
Art. 219(1) deducts — "adjusted for any currency and maturity mismatches" — and
column 0130 is the collateral that is NOT the deposit.

Three things are asserted, each on real pipeline output:

1. THE RULE ITSELF, on the registered ``netting`` portfolio. The Bank's
   ``boe_b0471`` (Error) and ``boe_b0556`` (Warning), restated cell by cell over
   every row of every OF 07.00 sheet. That portfolio is same-currency and
   maturity-matched, so it shows the double count and cannot show WHICH value
   column 0035 should carry.
2. THE VALUE, on ``reporting_netting_mismatch_portfolio``: a deposit shorter
   than its loan (Art. 219(3)), beside genuine collateral. There the adjusted
   value (173,626.57) and the allocation (300,000) differ, and column 0130 has
   a part that is not netting at all.
3. CRR DOES NOT MOVE. C 07.00 has no column 0035; the deposit stays financial
   collateral in column 0130 and the chain ties as it always did. The cell-exact
   proof that nothing moved is the committed ``netting_crr`` golden; the pins
   here say what the unmoved figures ARE.

References:
- PS1/26 Art. 219(1)-(3), Art. 223(3); CRR Art. 219, Art. 237-239
- PS1/26 Annex II, OF 07.00 columns 0035, 0040, 0130, 0140, 0150, 0200
- Bank of England validation rules boe_b0471, boe_b0556 (OF07.00.01.01)
- docs/development/escape-log.md, 2026-09-05
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from tests.fixtures import reporting_netting_mismatch_portfolio as mismatch
from tests.fixtures.raw_bundle import make_raw_bundle
from tests.fixtures.reporting_netting_portfolio import (
    EXPOSURE_VALUE_ENABLED,
    GROSS_ON_BS,
    TOTAL_NETTING_ENABLED,
    build_reporting_netting_bundle,
)

from rwa_calc.contracts.bundles import RawDataBundle
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import COUNTERPARTY_SCHEMA, FACILITY_MAPPING_SCHEMA, LOAN_SCHEMA
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from rwa_calc.reporting.corep.generator import COREPGenerator

_FRAMEWORK: dict[str, str] = {"crr": "CRR", "b31": "BASEL_3_1"}
_REGIMES: tuple[str, ...] = tuple(_FRAMEWORK)

#: (1 - CCF) per off-balance-sheet bucket column, per regime. Basel 3.1 is the
#: published ``boe_b0471``; CRR has no 40% bucket and its column 0160 is the 0%
#: bucket (``tests/acceptance/reporting/test_reporting_offbs_golden.py`` pins
#: both schedules against a portfolio that has off-balance-sheet items).
_CONVERTED_AWAY: dict[str, dict[str, float]] = {
    "b31": {"0160": 0.9, "0170": 0.8, "0171": 0.6, "0180": 0.5},
    "crr": {"0160": 1.0, "0170": 0.8, "0180": 0.5},
}

_ABS_TOLERANCE: float = 0.005  # half a penny on figures of millions


def _config(regime: str) -> CalculationConfig:
    """STANDARDISED, at the reporting dates the netting goldens use."""
    if regime == "crr":
        return CalculationConfig.crr(
            reporting_date=date(2025, 12, 31), permission_mode=PermissionMode.STANDARDISED
        )
    return CalculationConfig.basel_3_1(
        reporting_date=date(2027, 6, 1), permission_mode=PermissionMode.STANDARDISED
    )


def _generate(regime: str, bundle: RawDataBundle) -> tuple[pl.DataFrame, dict[str, pl.DataFrame]]:
    """Run one portfolio through one regime: (sealed ledger, C 07.00 sheets)."""
    result = PipelineOrchestrator().run_with_data(bundle, _config(regime))
    corep = COREPGenerator().generate_from_lazyframe(
        result.results,
        framework=_FRAMEWORK[regime],
        output_floor_summary=result.output_floor_summary,
    )
    assert corep.c07_00, f"{regime}: no C 07.00 sheet was emitted at all"
    return result.results.collect(), corep.c07_00


def _cell(sheet: pl.DataFrame, row_ref: str, col: str) -> float | None:
    if col not in sheet.columns:
        return None
    row = sheet.filter(pl.col("row_ref") == row_ref)
    return None if row.height == 0 else row[col][0]


def _exposure_value_identity_breaches(regime: str, sheets: dict[str, pl.DataFrame]) -> list[str]:
    """Every (sheet, row) where the published exposure-value identity fails.

        {c0200} = {c0150} - sum((1 - CCF_bucket) x {c bucket})      boe_b0471
        {c0200} <= {c0150}                                          boe_b0556

    Evaluated wherever BOTH column 0150 and column 0200 are reported. An empty
    bucket cell is read as zero, as the published rule reads it.
    """
    breaches: list[str] = []
    evaluated = 0
    for name, sheet in sheets.items():
        for row in sheet.iter_rows(named=True):
            fully_adjusted, exposure_value = row.get("0150"), row.get("0200")
            if fully_adjusted is None or exposure_value is None:
                continue
            evaluated += 1
            converted_away = sum(
                weight * (row.get(col) or 0.0) for col, weight in _CONVERTED_AWAY[regime].items()
            )
            where = f"{regime} {name} r{row['row_ref']}"
            if abs(exposure_value - (fully_adjusted - converted_away)) > _ABS_TOLERANCE:
                breaches.append(
                    f"{where}: c0200 {exposure_value:,.2f} != c0150 {fully_adjusted:,.2f} "
                    f"- converted-away {converted_away:,.2f}"
                )
            if exposure_value > fully_adjusted + _ABS_TOLERANCE:
                breaches.append(
                    f"{where}: c0200 {exposure_value:,.2f} > c0150 {fully_adjusted:,.2f}"
                )
    assert evaluated, f"{regime}: no row reports both c0150 and c0200 - the identity ran on nothing"
    return breaches


# =============================================================================
# 1. The rule itself, on the registered netting portfolio
# =============================================================================


def test_of07_exposure_value_identity_holds_on_the_netting_portfolio() -> None:
    """``boe_b0471`` and ``boe_b0556`` hold on every row of every OF 07.00 sheet.

    Arrange: the registered ``netting`` portfolio under Basel 3.1.
    Act:     generate OF 07.00 and evaluate both rules on every row that reports
             columns 0150 and 0200.
    Assert:  no breach — and the sheets really do carry a netting adjustment, so
             the identity is not holding on a book with nothing to deduct.
    """
    # Arrange + Act
    _ledger, sheets = _generate("b31", build_reporting_netting_bundle())

    # Assert — adequacy first (LESSONS C11): the deduction under test is present.
    netted = {
        name: _cell(sheet, "0010", "0035")
        for name, sheet in sheets.items()
        if (_cell(sheet, "0010", "0035") or 0.0) != 0.0
    }
    assert netted, (
        "no OF 07.00 sheet reports a non-zero column 0035, so the identity below "
        "would hold whether or not the netting were deducted twice"
    )
    assert {"corporate", "total"} <= set(sheets), sorted(sheets)

    breaches = _exposure_value_identity_breaches("b31", sheets)
    assert breaches == [], "\n".join(breaches)


@pytest.mark.parametrize("sheet_key", ["corporate", "total"])
@pytest.mark.parametrize("row_ref", ["0010", "0070"])
def test_of07_netting_portfolio_reports_the_deposit_in_column_0035_only(
    sheet_key: str, row_ref: str
) -> None:
    """The waterfall of the netted corporate book, cell by cell.

    Column 0130 was -3,000,000 and column 0150 was 16,000,000 before the fix
    (the deposit deducted twice); they are 0.0 and 19,000,000 — re-anchored here
    from the figures recorded in the 2026-09-05 escape-log entry.

    Arrange: the registered ``netting`` portfolio under Basel 3.1.
    Act:     generate OF 07.00.
    Assert:  0010 22,000,000; 0035 -3,000,000; 0040 19,000,000; 0130 0.0;
             0150 19,000,000; 0200 19,000,000.
    """
    # Arrange + Act
    _ledger, sheets = _generate("b31", build_reporting_netting_bundle())
    sheet = sheets[sheet_key]

    # Assert
    assert _cell(sheet, row_ref, "0010") == pytest.approx(GROSS_ON_BS)
    assert _cell(sheet, row_ref, "0035") == pytest.approx(-TOTAL_NETTING_ENABLED)
    assert _cell(sheet, row_ref, "0040") == pytest.approx(EXPOSURE_VALUE_ENABLED)
    assert _cell(sheet, row_ref, "0130") == pytest.approx(0.0, abs=_ABS_TOLERANCE)
    assert _cell(sheet, row_ref, "0150") == pytest.approx(EXPOSURE_VALUE_ENABLED)
    assert _cell(sheet, row_ref, "0200") == pytest.approx(EXPOSURE_VALUE_ENABLED)


# =============================================================================
# 2. The value: adjusted, not allocated — and collateral beside it
# =============================================================================


@pytest.mark.parametrize("regime", _REGIMES)
def test_ledger_carries_the_adjusted_netting_value_beside_the_allocation(regime: str) -> None:
    """The sealed ledger holds both netting figures, and they differ on CP-M.

    Arrange: the mismatch portfolio (hand calculation in its module docstring).
    Act:     run the pipeline.
    Assert:  per loan, ``on_bs_netting_amount`` is the Art. 219 allocation and
             ``on_bs_netting_adjusted_value`` the Art. 219(3)-scaled value; the
             collateral column holds the adjusted netting PLUS the pledge.
    """
    # Arrange — adequacy: the two carriers must be able to disagree here.
    assert mismatch.NETTING_ADJUSTED[mismatch.LN_M] < mismatch.NETTING_ALLOCATION[mismatch.LN_M]
    assert mismatch.NETTING_ADJUSTED[mismatch.LN_N] == mismatch.NETTING_ALLOCATION[mismatch.LN_N]

    # Act
    config = _config(regime)
    ledger, _sheets = _generate(
        regime, mismatch.build_netting_mismatch_bundle(config.reporting_date)
    )
    rows = {row["exposure_reference"]: row for row in ledger.to_dicts()}

    # Assert
    for loan in (mismatch.LN_M, mismatch.LN_N, mismatch.LN_P):
        row = rows[loan]
        assert row["on_bs_netting_amount"] == pytest.approx(mismatch.NETTING_ALLOCATION[loan])
        assert row["on_bs_netting_adjusted_value"] == pytest.approx(
            mismatch.NETTING_ADJUSTED[loan]
        ), f"{regime} {loan}"
        assert row["collateral_adjusted_value"] == pytest.approx(
            mismatch.NETTING_ADJUSTED[loan] + mismatch.PLEDGE_ADJUSTED[loan]
        ), f"{regime} {loan}"
    assert ledger["ead_final"].sum() == pytest.approx(mismatch.EXPOSURE_VALUE)


@pytest.mark.parametrize("row_ref", ["0010", "0070"])
def test_of07_column_0035_is_the_adjusted_value_and_0130_the_collateral_alone(
    row_ref: str,
) -> None:
    """Column 0035 carries the adjusted netting; column 0130 only the pledges.

        0150 = 0040 - (the genuinely collateral part) = 0200

    Before the fix this sheet read 0035 -300,000 (the allocation), 0130
    -292,047.62 (netting AND pledges) and 0150 1,207,952.38 against a column
    0200 of 1,507,952.38.

    Arrange: the mismatch portfolio under Basel 3.1.
    Act:     generate OF 07.00.
    Assert:  the corporate sheet's total and on-balance-sheet rows carry the
             hand-calculated waterfall, and column 0140 holds the pledge's own
             maturity adjustment — not the deposit's.
    """
    # Arrange — adequacy: netting and collateral are different money here.
    assert mismatch.TOTAL_NETTING_ADJUSTED != mismatch.TOTAL_NETTING_ALLOCATION
    assert mismatch.TOTAL_PLEDGE_ADJUSTED > 0.0
    assert mismatch.NETTING_ADJUSTMENT > 0.0 and mismatch.PLEDGE_ADJUSTMENT > 0.0

    # Act
    config = _config("b31")
    _ledger, sheets = _generate(
        "b31", mismatch.build_netting_mismatch_bundle(config.reporting_date)
    )
    sheet = sheets["corporate"]

    # Assert
    net_of_netting = mismatch.GROSS - mismatch.TOTAL_NETTING_ADJUSTED
    assert _cell(sheet, row_ref, "0010") == pytest.approx(mismatch.GROSS)
    assert _cell(sheet, row_ref, "0035") == pytest.approx(-mismatch.TOTAL_NETTING_ADJUSTED)
    assert _cell(sheet, row_ref, "0040") == pytest.approx(net_of_netting)
    assert _cell(sheet, row_ref, "0130") == pytest.approx(-mismatch.TOTAL_PLEDGE_ADJUSTED)
    assert _cell(sheet, row_ref, "0140") == pytest.approx(-mismatch.PLEDGE_ADJUSTMENT)
    assert _cell(sheet, row_ref, "0150") == pytest.approx(
        net_of_netting - mismatch.TOTAL_PLEDGE_ADJUSTED
    )
    assert _cell(sheet, row_ref, "0150") == pytest.approx(mismatch.EXPOSURE_VALUE)
    assert _cell(sheet, row_ref, "0200") == pytest.approx(mismatch.EXPOSURE_VALUE)


@pytest.mark.parametrize("regime", _REGIMES)
def test_exposure_value_identity_holds_on_the_mismatch_portfolio(regime: str) -> None:
    """The same identity, where netting, a mismatch and collateral all meet.

    Parametrised over both regimes and required to hold in each (LESSONS C7):
    CRR satisfies it through column 0130 alone, Basel 3.1 through 0035 and 0130
    together, and a carrier that served one basis could break the other.
    """
    config = _config(regime)
    _ledger, sheets = _generate(
        regime, mismatch.build_netting_mismatch_bundle(config.reporting_date)
    )
    breaches = _exposure_value_identity_breaches(regime, sheets)
    assert breaches == [], "\n".join(breaches)


def _over_netted_bundle() -> RawDataBundle:
    """A GBP 300 deposit netting a GBP 100 loan, beside an un-netted GBP 1,000 loan.

    One unrated corporate, one currency, one maturity date: the only thing in
    play is that the deposit is LARGER than the loan it nets.
    """
    common: dict = {
        "counterparty_reference": "OVN-CP",
        "product_type": "term_loan",
        "currency": "GBP",
        "value_date": date(2020, 1, 1),
        "maturity_date": date(2031, 12, 31),
        "seniority": "senior",
        "interest": 0.0,
    }
    loans = [
        {"loan_reference": "OVN-DEP", "drawn_amount": -300.0, **common},
        {"loan_reference": "OVN-LN", "drawn_amount": 100.0, **common},
        {"loan_reference": "OVN-PLAIN", "drawn_amount": 1_000.0, **common},
    ]
    agreements = {"OVN-DEP": "OVN-AGR", "OVN-LN": "OVN-AGR", "OVN-PLAIN": None}
    for loan in loans:
        loan["netting_agreement_reference"] = agreements[loan["loan_reference"]]
    counterparty = {
        "counterparty_reference": "OVN-CP",
        "entity_type": "corporate",
        "country_code": "GB",
        "annual_revenue": 250_000_000.0,
    }
    return make_raw_bundle(
        counterparties=pl.DataFrame(
            [counterparty], schema_overrides=dtypes_of(COUNTERPARTY_SCHEMA)
        ),
        loans=pl.DataFrame(loans, schema_overrides=dtypes_of(LOAN_SCHEMA)),
        facility_mappings=pl.DataFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
    )


def test_of07_an_over_netted_loan_reduces_the_sheet_by_its_own_exposure_only() -> None:
    """Column 0035 is the REDUCTION in exposure value: 100, not the 300 deposit.

    PS1/26 Art. 219(1) floors the netted exposure value at zero, so a GBP 300
    deposit takes GBP 100 off a GBP 100 loan. The engine carries the whole 300 as
    the deposit's value and floors the exposure afterwards; reporting the 300
    would take the other 200 off the un-netted loan beside it — column 0040 of
    800 against an exposure value of 1,000.

    Arrange: the over-netted pair and an un-netted loan, under Basel 3.1.
    Act:     run the pipeline and generate OF 07.00.
    Assert:  the ledger carries the uncapped 300; the sheet reports 0035 -100,
             0040 = 0150 = 0200 = 1,000, and the identity holds on every row.
    """
    # Arrange + Act
    ledger, sheets = _generate("b31", _over_netted_bundle())
    netted = ledger.filter(pl.col("exposure_reference") == "OVN-LN").to_dicts()[0]
    sheet = sheets["corporate"]

    # Assert — the carrier is the valuation, the cell is the reduction
    assert netted["on_bs_netting_adjusted_value"] == pytest.approx(300.0)
    assert netted["ead_final"] == pytest.approx(0.0)
    assert _cell(sheet, "0010", "0010") == pytest.approx(1_100.0)
    assert _cell(sheet, "0010", "0035") == pytest.approx(-100.0)
    assert _cell(sheet, "0010", "0040") == pytest.approx(1_000.0)
    assert _cell(sheet, "0010", "0130") == pytest.approx(0.0, abs=_ABS_TOLERANCE)
    assert _cell(sheet, "0010", "0150") == pytest.approx(1_000.0)
    assert _cell(sheet, "0010", "0200") == pytest.approx(1_000.0)
    assert _exposure_value_identity_breaches("b31", sheets) == []


# =============================================================================
# 3. CRR does not move
# =============================================================================


@pytest.mark.parametrize("sheet_key", ["corporate", "total"])
def test_crr_c07_still_nets_the_deposit_once_through_column_0130(sheet_key: str) -> None:
    """C 07.00 has no column 0035: the deposit is financial collateral there.

    These figures are the ones the committed ``netting_crr`` golden holds; the
    test passes before and after the Basel 3.1 fix, which is its purpose.

    Arrange: the registered ``netting`` portfolio under CRR.
    Act:     generate C 07.00.
    Assert:  no column 0035; 0040 22,000,000; 0130 -3,000,000; 0150 = 0200 =
             19,000,000; and the exposure-value identity holds on every row.
    """
    # Arrange + Act
    _ledger, sheets = _generate("crr", build_reporting_netting_bundle())
    sheet = sheets[sheet_key]

    # Assert
    assert "0035" not in sheet.columns
    assert _cell(sheet, "0010", "0040") == pytest.approx(GROSS_ON_BS)
    assert _cell(sheet, "0010", "0130") == pytest.approx(-TOTAL_NETTING_ENABLED)
    assert _cell(sheet, "0010", "0150") == pytest.approx(EXPOSURE_VALUE_ENABLED)
    assert _cell(sheet, "0010", "0200") == pytest.approx(EXPOSURE_VALUE_ENABLED)
    assert _exposure_value_identity_breaches("crr", sheets) == []


def test_crr_c07_keeps_the_deposit_and_its_adjustment_in_the_collateral_columns() -> None:
    """Under CRR the mismatched deposit shows in 0130 and its scaling in 0140.

    The CRR twin of the Basel 3.1 waterfall above, from the same portfolio: the
    netting is not carved out of the collateral columns, because CRR has no
    other column to report it in.

    Arrange: the mismatch portfolio under CRR.
    Act:     generate C 07.00.
    Assert:  0130 = -(adjusted netting + pledges); 0140 = -(both adjustments);
             0150 = 0200 = the exposure value.
    """
    # Arrange + Act
    config = _config("crr")
    _ledger, sheets = _generate(
        "crr", mismatch.build_netting_mismatch_bundle(config.reporting_date)
    )
    sheet = sheets["corporate"]

    # Assert
    assert "0035" not in sheet.columns
    assert _cell(sheet, "0010", "0040") == pytest.approx(mismatch.GROSS)
    assert _cell(sheet, "0010", "0130") == pytest.approx(
        -(mismatch.TOTAL_NETTING_ADJUSTED + mismatch.TOTAL_PLEDGE_ADJUSTED)
    )
    assert _cell(sheet, "0010", "0140") == pytest.approx(
        -(mismatch.NETTING_ADJUSTMENT + mismatch.PLEDGE_ADJUSTMENT)
    )
    assert _cell(sheet, "0010", "0150") == pytest.approx(mismatch.EXPOSURE_VALUE)
    assert _cell(sheet, "0010", "0200") == pytest.approx(mismatch.EXPOSURE_VALUE)
