"""
C 07.00 / OF 07.00 cols 0130 / 0140 — the per-exposure collateral cap and the
Simple-Method exclusion, on synthetic frames in the sealed ledger's shape.

Pipeline position:
    sealed-ledger-shaped LazyFrame -> C 07.00 generator -> per-class sheets

What is pinned, one mechanism per test:

- Col 0130 (Cvam) is capped PER EXPOSURE at what is left of that exposure
  after col 0030 (provisions), col 0035 (Basel 3.1 netting) and the col
  0050-0080 substitution block — the row's own share of col 0110, the
  "volatility adjusted value EVA" EBA Q&A 2015_2010 caps it at (col 0120 is
  not modelled). Uncapped, one loan's unused collateral came off every other
  loan on the sheet.
- Col 0140 is the joint adjustment C - Cvam AS CALCULATED, not scaled by the
  cap (the Q&A's worked example keeps c140 at -10 while capping c130).
- A Simple-Method row (Art. 222; the ledger carries a non-null
  ``fcsm_collateral_value``) reports nothing in cols 0130 / 0140: Annex II
  says those columns "shall be reported for exposures subject to the Financial
  Collateral Comprehensive Method".

The end-to-end statement of both, on real pipeline output, is
``tests/acceptance/reporting/test_c07_collateral_columns.py``.

References:
- CRR / PS1/26 Art. 222, Art. 223(5); COREP / PS1/26 Annex II C 07.00
  cols 0050-0100 (block heading), 0130, 0140, 0150
- EBA Q&A 2015_2010
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._builders import _get_total_row

_FRAMEWORKS: tuple[str, ...] = ("CRR", "BASEL_3_1")


def _book(rows: list[dict]) -> pl.LazyFrame:
    """Corporate SA loans at a 100% weight; each row overrides what it needs."""
    defaults: dict = {
        "approach_applied": "standardised",
        "exposure_class": "corporate",
        "exposure_type": "loan",
        "undrawn_amount": 0.0,
        "scra_provision_amount": 0.0,
        "gcra_provision_amount": 0.0,
        "collateral_adjusted_value": 0.0,
        "collateral_market_value": 0.0,
        "risk_weight": 1.0,
    }
    records = [{**defaults, **row} for row in rows]
    for record in records:
        record.setdefault("rwa_final", record["ead_final"])
    return pl.LazyFrame(records, infer_schema_length=None)


def _corporate_total(frame: pl.LazyFrame, framework: str) -> dict:
    bundle = LedgerShimCorepGenerator().generate_from_lazyframe(frame, framework=framework)
    return _get_total_row(bundle.c07_00["corporate"]).to_dicts()[0]


# A 100 loan secured by 300 of matched cash beside an unsecured 1,000 loan.
_OVER_COLLATERALISED = [
    {
        "exposure_reference": "OVER",
        "counterparty_reference": "CP_A",
        "drawn_amount": 100.0,
        "collateral_adjusted_value": 300.0,
        "collateral_market_value": 300.0,
        "ead_final": 0.0,
    },
    {
        "exposure_reference": "UNSECURED",
        "counterparty_reference": "CP_A",
        "drawn_amount": 1000.0,
        "ead_final": 1000.0,
    },
]


class TestCollateralIsCappedAtTheExposureItSecures:
    """Col 0130 is each exposure's Cvam, no more than that exposure."""

    @pytest.mark.parametrize("framework", _FRAMEWORKS)
    def test_unused_collateral_does_not_come_off_another_loan(self, framework: str) -> None:
        """A 100 loan with 300 of collateral reduces col 0150 by 100, not 300.

        Arrange: the over-collateralised loan beside an unsecured 1,000.
        Act:     generate the corporate sheet.
        Assert:  0130 = -100; 0150 = 0200 = 1,000 (it was 800 before the cap).
        """
        # Arrange
        frame = _book(_OVER_COLLATERALISED)

        # Act
        total = _corporate_total(frame, framework)

        # Assert
        assert total["0130"] == pytest.approx(-100.0)
        assert total["0150"] == pytest.approx(1000.0)
        assert total["0200"] == pytest.approx(1000.0)

    @pytest.mark.parametrize("framework", _FRAMEWORKS)
    def test_collateral_below_the_exposure_is_untouched(self, framework: str) -> None:
        """The cap binds only where the collateral over-runs: 200 against 500 stays 200.

        Arrange: the over-collateralised pair plus a 500 loan with 200 of cash.
        Act:     generate the corporate sheet.
        Assert:  0130 = -(100 + 200) = -300; 0150 = 1,300.
        """
        # Arrange
        frame = _book(
            [
                *_OVER_COLLATERALISED,
                {
                    "exposure_reference": "PART",
                    "counterparty_reference": "CP_B",
                    "drawn_amount": 500.0,
                    "collateral_adjusted_value": 200.0,
                    "collateral_market_value": 200.0,
                    "ead_final": 300.0,
                },
            ]
        )

        # Act
        total = _corporate_total(frame, framework)

        # Assert
        assert total["0130"] == pytest.approx(-300.0)
        assert total["0150"] == pytest.approx(1300.0)

    @pytest.mark.parametrize("framework", _FRAMEWORKS)
    def test_the_cap_is_the_exposure_net_of_provisions(self, framework: str) -> None:
        """A 100 loan carrying a 10 provision has 90 for its collateral to secure.

        Arrange: a 100 loan, provision 10, collateral 300.
        Act:     generate the corporate sheet.
        Assert:  0030 = -10, 0130 = -90, 0150 = 0.
        """
        # Arrange
        frame = _book(
            [
                {
                    "exposure_reference": "OVER",
                    "counterparty_reference": "CP_A",
                    "drawn_amount": 100.0,
                    "scra_provision_amount": 10.0,
                    "collateral_adjusted_value": 300.0,
                    "collateral_market_value": 300.0,
                    "ead_final": 0.0,
                }
            ]
        )

        # Act
        total = _corporate_total(frame, framework)

        # Assert
        assert total["0030"] == pytest.approx(-10.0)
        assert total["0130"] == pytest.approx(-90.0)
        assert total["0150"] == pytest.approx(0.0)

    @pytest.mark.parametrize("framework", _FRAMEWORKS)
    def test_the_cap_is_what_the_substitution_block_leaves(self, framework: str) -> None:
        """The covered part leaves through col 0090 first; collateral secures the rest.

        Arrange: a 100 loan, 60 of it guaranteed, with 300 of collateral.
        Act:     generate the corporate sheet.
        Assert:  0050 = -60, 0110 = 40, 0130 = -40, 0150 = 0.
        """
        # Arrange
        frame = _book(
            [
                {
                    "exposure_reference": "OVER",
                    "counterparty_reference": "CP_A",
                    "drawn_amount": 100.0,
                    "guaranteed_portion": 60.0,
                    "protection_type": "guarantee",
                    "collateral_adjusted_value": 300.0,
                    "collateral_market_value": 300.0,
                    "ead_final": 0.0,
                }
            ]
        )

        # Act
        total = _corporate_total(frame, framework)

        # Assert
        assert total["0050"] == pytest.approx(-60.0)
        assert total["0110"] == pytest.approx(40.0)
        assert total["0130"] == pytest.approx(-40.0)
        assert total["0150"] == pytest.approx(0.0)

    def test_basel_3_1_caps_the_collateral_after_the_netting_column(self) -> None:
        """Col 0035 takes the netted deposit first; genuine collateral secures what is left.

        PS1/26 Art. 223(3) starts the comprehensive method from the exposure
        value after Art. 219 netting.

        Arrange: a 100 loan netted by an 80 deposit and secured by 50 of cash
                 (the ledger's collateral columns hold both: 130).
        Act:     generate OF 07.00.
        Assert:  0035 = -80, 0130 = -20, 0150 = 0.
        """
        # Arrange
        frame = _book(
            [
                {
                    "exposure_reference": "NETTED_AND_SECURED",
                    "counterparty_reference": "CP_A",
                    "drawn_amount": 100.0,
                    "on_bs_netting_amount": 80.0,
                    "on_bs_netting_adjusted_value": 80.0,
                    "collateral_adjusted_value": 130.0,
                    "collateral_market_value": 130.0,
                    "ead_final": 0.0,
                }
            ]
        )

        # Act
        total = _corporate_total(frame, "BASEL_3_1")

        # Assert
        assert total["0035"] == pytest.approx(-80.0)
        assert total["0130"] == pytest.approx(-20.0)
        assert total["0150"] == pytest.approx(0.0)

    def test_crr_caps_a_netted_deposit_larger_than_its_loan(self) -> None:
        """CRR has no col 0035, so the deposit is col 0130 collateral — capped there.

        Arrange: a 100 loan netted by a 300 deposit beside an un-netted 1,000.
        Act:     generate C 07.00.
        Assert:  0130 = -100; 0150 = 0200 = 1,000.
        """
        # Arrange
        frame = _book(
            [
                {
                    **_OVER_COLLATERALISED[0],
                    "on_bs_netting_amount": 300.0,
                    "on_bs_netting_adjusted_value": 300.0,
                },
                {**_OVER_COLLATERALISED[1], "on_bs_netting_amount": 0.0},
            ]
        )

        # Act
        total = _corporate_total(frame, "CRR")

        # Assert
        assert total["0130"] == pytest.approx(-100.0)
        assert total["0150"] == pytest.approx(1000.0)
        assert total["0200"] == pytest.approx(1000.0)


class TestTheAdjustmentIsReportedAsCalculated:
    """Col 0140 is C - Cvam for the pledge, whatever the cap does to col 0130."""

    @pytest.mark.parametrize("framework", _FRAMEWORKS)
    def test_column_0140_is_not_scaled_by_the_cap(self, framework: str) -> None:
        """EBA Q&A 2015_2010: c130 capped, c140 left at its calculated value.

        Arrange: a 100 loan secured by collateral of market value 500 whose
                 adjusted value is 200.
        Act:     generate the corporate sheet.
        Assert:  0130 = -100 (capped); 0140 = -300 (500 - 200), not -150.
        """
        # Arrange
        frame = _book(
            [
                {
                    "exposure_reference": "HAIRCUT",
                    "counterparty_reference": "CP_A",
                    "drawn_amount": 100.0,
                    "collateral_adjusted_value": 200.0,
                    "collateral_market_value": 500.0,
                    "ead_final": 0.0,
                }
            ]
        )

        # Act
        total = _corporate_total(frame, framework)

        # Assert
        assert total["0130"] == pytest.approx(-100.0)
        assert total["0140"] == pytest.approx(-300.0)


class TestSimpleMethodRowsAreOutsideTheComprehensiveColumns:
    """Cols 0120-0140 are for exposures under the Comprehensive Method only."""

    @pytest.mark.parametrize("framework", _FRAMEWORKS)
    def test_a_simple_method_row_reports_no_adjustment(self, framework: str) -> None:
        """The ledger keeps the market value of Simple-Method collateral; col 0140 does not.

        Arrange: a 1,000 loan with 300 of Simple-Method cash — adjusted value
                 zeroed by the engine, market value kept, ``fcsm_collateral_value``
                 300.
        Act:     generate the corporate sheet.
        Assert:  0070 = -300; 0130 = 0; 0140 = 0 (it was -300).
        """
        # Arrange
        frame = _book(
            [
                {
                    "exposure_reference": "FCSM",
                    "counterparty_reference": "CP_A",
                    "drawn_amount": 1000.0,
                    "collateral_market_value": 300.0,
                    "fcsm_collateral_value": 300.0,
                    "ead_final": 1000.0,
                    "rwa_final": 700.0,
                }
            ]
        )

        # Act
        total = _corporate_total(frame, framework)

        # Assert
        assert total["0070"] == pytest.approx(-300.0)
        assert total["0130"] == pytest.approx(0.0)
        assert total["0140"] == pytest.approx(0.0)

    @pytest.mark.parametrize("framework", _FRAMEWORKS)
    def test_a_null_simple_method_carrier_is_the_comprehensive_method(self, framework: str) -> None:
        """Under the Comprehensive election the ledger seals the carrier as null.

        The control for the test above: the column exists but is null, so the
        row is a Comprehensive-Method row and col 0140 keeps its adjustment.

        Arrange: a 500 loan, collateral market 150 / adjusted 120, null
                 ``fcsm_collateral_value``.
        Act:     generate the corporate sheet.
        Assert:  0130 = -120; 0140 = -30.
        """
        # Arrange
        frame = _book(
            [
                {
                    "exposure_reference": "FCCM",
                    "counterparty_reference": "CP_A",
                    "drawn_amount": 500.0,
                    "collateral_adjusted_value": 120.0,
                    "collateral_market_value": 150.0,
                    "fcsm_collateral_value": None,
                    "ead_final": 380.0,
                }
            ]
        ).with_columns(pl.col("fcsm_collateral_value").cast(pl.Float64))

        # Act
        total = _corporate_total(frame, framework)

        # Assert
        assert total["0130"] == pytest.approx(-120.0)
        assert total["0140"] == pytest.approx(-30.0)
