"""COREP C 07.00 / OF 07.00 — on-balance-sheet netting (col 0035) and the
financial-collateral columns it must not be counted in twice (0130, 0140).

Per-template file in the Phase 7 Sn convention, alongside ``test_c07_ccf_buckets.py``
and ``test_c07_provisions.py``. The five ``TestOnBSNetting`` C 07.00 cases moved
here from ``test_cross.py`` (which keeps the C 08.01 ones) when the column's
carrier changed.

What the columns mean (PS1/26 Annex II, OF 07.00):

- 0035 "(-) Adjustment to exposure value due to on-balance sheet netting" —
  "the reduction in exposure value due to on-balance sheet netting determined in
  accordance with Article 219". Art. 219(1) deducts the deposit "adjusted for any
  currency and maturity mismatches" and floors the result at zero, so the
  reduction is the ADJUSTED value, never more than the exposure it reduces.
- 0040 "Exposure net of value adjustments, provisions and on-balance sheet
  netting" — "sum of columns 0010, 0030, and 0035".
- 0130 "(-) Financial collateral adjusted value (Cvam)" and 0140 "(-) Of which:
  volatility and maturity adjustments" — the Financial Collateral Comprehensive
  Method, which Art. 223(3) starts from the exposure value AFTER Art. 219.

The engine carries the netted deposit as synthetic cash collateral, so on the
sealed ledger ``collateral_adjusted_value`` and ``collateral_market_value``
INCLUDE it. Two more carriers say how much of each is the deposit:
``on_bs_netting_adjusted_value`` and ``on_bs_netting_amount``. Under Basel 3.1
the template reports the deposit in 0035 and takes it OUT of 0130 / 0140; under
CRR there is no column 0035 and the deposit stays in the collateral columns.

The end-to-end proof over real pipeline output, including the published
identity ``boe_b0471``, is
``tests/acceptance/reporting/test_of07_netting_single_deduction.py``.

References:
- PS1/26 Art. 219(1)-(3), Art. 223(3); PS1/26 Annex II (OF 07.00)
- COREP Annex II §1.3 (the "(-)" sign convention)
- docs/development/escape-log.md, 2026-09-05
"""

from __future__ import annotations

import polars as pl
import pytest

from tests.fixtures.recon_ledger import LedgerShimCorepGenerator
from tests.unit.reporting.corep._builders import _get_total_row, _sa_results

# ---------------------------------------------------------------------------
# A netted book in the sealed ledger's shape
# ---------------------------------------------------------------------------
#
#   loan            gross   netting           pledge            exposure
#                           alloc.  adjusted  market  adjusted  value
#   NET_ONLY        1,000     300      266       -       -         734
#   NET_AND_PLEDGE  2,000     400      400     600     500       1,100
#   PLEDGE_ONLY       500       -        -     150     120         380
#   PLAIN             300       -        -       -       -         300
#                   -----   -----    -----    ----    ----       -----
#                   3,800     700      666     750     620       2,514
#
# NET_ONLY's deposit takes a mismatch haircut (300 -> 266); NET_AND_PLEDGE's
# does not. The collateral columns hold netting AND pledge, as the ledger does.
_NETTING_ALLOCATION = [300.0, 400.0, 0.0, 0.0]
_NETTING_ADJUSTED = [266.0, 400.0, 0.0, 0.0]
_PLEDGE_MARKET = [0.0, 600.0, 150.0, 0.0]
_PLEDGE_ADJUSTED = [0.0, 500.0, 120.0, 0.0]
_GROSS = [1000.0, 2000.0, 500.0, 300.0]
_EXPOSURE_VALUE = [734.0, 1100.0, 380.0, 300.0]


def _netted_book(**overrides: list) -> pl.LazyFrame:
    """Four corporate loans: netting only, netting + pledge, pledge only, plain."""
    data: dict[str, list] = {
        "exposure_reference": ["NET_ONLY", "NET_AND_PLEDGE", "PLEDGE_ONLY", "PLAIN"],
        "approach_applied": ["standardised"] * 4,
        "exposure_class": ["corporate"] * 4,
        "counterparty_reference": ["CP_A", "CP_B", "CP_C", "CP_D"],
        "drawn_amount": _GROSS,
        "undrawn_amount": [0.0] * 4,
        "scra_provision_amount": [0.0] * 4,
        "gcra_provision_amount": [0.0] * 4,
        "on_bs_netting_amount": _NETTING_ALLOCATION,
        "on_bs_netting_adjusted_value": _NETTING_ADJUSTED,
        "collateral_adjusted_value": [
            n + p for n, p in zip(_NETTING_ADJUSTED, _PLEDGE_ADJUSTED, strict=True)
        ],
        "collateral_market_value": [
            n + p for n, p in zip(_NETTING_ALLOCATION, _PLEDGE_MARKET, strict=True)
        ],
        "ead_final": _EXPOSURE_VALUE,
        "rwa_final": _EXPOSURE_VALUE,
        "risk_weight": [1.0] * 4,
    }
    data.update(overrides)
    return pl.LazyFrame(data)


def _corporate_total(frame: pl.LazyFrame, framework: str) -> dict:
    bundle = LedgerShimCorepGenerator().generate_from_lazyframe(frame, framework=framework)
    return _get_total_row(bundle.c07_00["corporate"]).to_dicts()[0]


class TestNettingIsDeductedOnce:
    """Basel 3.1: the deposit is in col 0035 and out of cols 0130 / 0140."""

    def test_b31_col_0035_is_the_adjusted_value_not_the_allocation(self) -> None:
        """Col 0035 sums the ADJUSTED netting (666), not the allocation (700).

        Arrange: the netted book, where one deposit is haircut 300 -> 266.
        Act:     generate OF 07.00.
        Assert:  0035 = -666 and 0040 = 3,800 - 666.
        """
        total = _corporate_total(_netted_book(), "BASEL_3_1")
        assert total["0035"] == pytest.approx(-666.0)
        assert total["0040"] == pytest.approx(3134.0)

    def test_b31_col_0130_is_the_collateral_that_is_not_the_deposit(self) -> None:
        """Col 0130 = collateral adjusted value LESS the netting part of it.

        Arrange: the netted book — collateral column 1,286 = 666 netting + 620 pledge.
        Act:     generate OF 07.00.
        Assert:  0130 = -620, the pledges alone.
        """
        total = _corporate_total(_netted_book(), "BASEL_3_1")
        assert total["0130"] == pytest.approx(-620.0)

    def test_b31_col_0140_is_the_pledges_own_adjustment(self) -> None:
        """Col 0140 is an "of which" of 0130, so it leaves the deposit out too.

        The pledges' market value less adjusted value is (600 - 500) + (150 - 120)
        = 130. The deposit's own haircut (300 - 266 = 34) is not an adjustment to
        any collateral col 0130 reports.
        """
        total = _corporate_total(_netted_book(), "BASEL_3_1")
        assert total["0140"] == pytest.approx(-130.0)

    def test_b31_fully_adjusted_value_equals_the_exposure_value(self) -> None:
        """0150 = 0040 - (the genuinely collateral part) = 0200 on a drawn book.

        The published ``boe_b0471`` with no off-balance-sheet item to convert.
        Before the fix 0150 was 1,814: 3,800 - 700 (allocation) - 1,286 (netting
        AND pledge) — the deposit deducted twice.
        """
        total = _corporate_total(_netted_book(), "BASEL_3_1")
        assert total["0150"] == pytest.approx(3134.0 - 620.0)
        assert total["0150"] == pytest.approx(sum(_EXPOSURE_VALUE))
        assert total["0200"] == pytest.approx(sum(_EXPOSURE_VALUE))

    def test_crr_keeps_the_deposit_in_the_collateral_columns(self) -> None:
        """CRR has no col 0035: 0130 / 0140 carry netting and pledge together.

        The same book, the same exposure value, reached through one column
        instead of two — CRR did not move.
        """
        total = _corporate_total(_netted_book(), "CRR")
        assert "0035" not in total
        assert total["0040"] == pytest.approx(3800.0)
        assert total["0130"] == pytest.approx(-1286.0)
        assert total["0140"] == pytest.approx(-(1450.0 - 1286.0))
        assert total["0150"] == pytest.approx(sum(_EXPOSURE_VALUE))
        assert total["0200"] == pytest.approx(sum(_EXPOSURE_VALUE))


class TestNettingReductionIsCappedAtTheExposure:
    """Col 0035 is the REDUCTION in exposure value, so no more than the exposure."""

    def test_an_over_netted_loan_reports_its_own_exposure_and_no_more(self) -> None:
        """A 300 deposit against a 100 loan reduces the exposure value by 100.

        Art. 219(1) floors the netted exposure value at zero. Reporting the whole
        300 would take 200 off the OTHER loan on the sheet: 0040 = 800 against an
        exposure value of 1,000.

        Arrange: a 100 loan netted by 300, and an un-netted 1,000 loan.
        Act:     generate OF 07.00.
        Assert:  0035 = -100; 0040 = 0150 = 0200 = 1,000.
        """
        frame = pl.LazyFrame(
            {
                "exposure_reference": ["OVER_NETTED", "UNNETTED"],
                "approach_applied": ["standardised"] * 2,
                "exposure_class": ["corporate"] * 2,
                "counterparty_reference": ["CP_A", "CP_B"],
                "drawn_amount": [100.0, 1000.0],
                "undrawn_amount": [0.0, 0.0],
                "scra_provision_amount": [0.0, 0.0],
                "gcra_provision_amount": [0.0, 0.0],
                "on_bs_netting_amount": [300.0, 0.0],
                "on_bs_netting_adjusted_value": [300.0, 0.0],
                "collateral_adjusted_value": [300.0, 0.0],
                "collateral_market_value": [300.0, 0.0],
                "ead_final": [0.0, 1000.0],
                "rwa_final": [0.0, 1000.0],
                "risk_weight": [1.0, 1.0],
            }
        )
        total = _corporate_total(frame, "BASEL_3_1")
        assert total["0035"] == pytest.approx(-100.0)
        assert total["0040"] == pytest.approx(1000.0)
        assert total["0130"] == pytest.approx(0.0)
        assert total["0150"] == pytest.approx(1000.0)
        assert total["0200"] == pytest.approx(1000.0)

    def test_the_cap_is_the_exposure_net_of_provisions(self) -> None:
        """Art. 219(1)(b)(i) nets against the Art. 111(1) value — the accounting
        value after specific credit risk adjustments — so col 0040 cannot go
        negative on a provisioned row.

        Arrange: a 100 loan carrying a 10 provision, netted by 300.
        Act:     generate OF 07.00.
        Assert:  0030 = -10, 0035 = -90, 0040 = 0.
        """
        frame = pl.LazyFrame(
            {
                "exposure_reference": ["OVER_NETTED"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "counterparty_reference": ["CP_A"],
                "drawn_amount": [100.0],
                "undrawn_amount": [0.0],
                "scra_provision_amount": [10.0],
                "gcra_provision_amount": [0.0],
                "on_bs_netting_amount": [300.0],
                "on_bs_netting_adjusted_value": [300.0],
                "collateral_adjusted_value": [300.0],
                "collateral_market_value": [300.0],
                "ead_final": [0.0],
                "rwa_final": [0.0],
                "risk_weight": [1.0],
            }
        )
        total = _corporate_total(frame, "BASEL_3_1")
        assert total["0030"] == pytest.approx(-10.0)
        assert total["0035"] == pytest.approx(-90.0)
        assert total["0040"] == pytest.approx(0.0)


class TestNettingCarrierEdgeCases:
    """Frames that do not carry the adjusted value, or carry none of it."""

    def test_a_null_carrier_deducts_nothing_and_leaves_col_0130_whole(self) -> None:
        """A typed-null carrier is "no netting known", not a crash and not a zero
        collateral value: col 0130 keeps the whole collateral column.

        Arrange: the netted book with the adjusted-value column all null.
        Act:     generate OF 07.00.
        Assert:  0035 = 0, 0130 = -1,286.
        """
        frame = _netted_book().with_columns(
            pl.lit(None, dtype=pl.Float64).alias("on_bs_netting_adjusted_value")
        )
        total = _corporate_total(frame, "BASEL_3_1")
        assert total["0035"] == pytest.approx(0.0)
        assert total["0130"] == pytest.approx(-1286.0)

    def test_a_simple_method_row_reports_the_deposit_as_simple_method_collateral(self) -> None:
        """Art. 222: the engine recognises the deposit as Simple-Method cash, so it
        shows in col 0070 and in NEITHER col 0035 nor cols 0130 / 0140.

        On the ledger a Simple-Method SA row has ``collateral_adjusted_value`` and
        the netting carrier both at zero while ``collateral_market_value`` and
        ``on_bs_netting_amount`` keep the deposit. Reading 0140 as market less
        adjusted alone would report the whole deposit as a "volatility
        adjustment" to collateral col 0130 does not hold.

        Arrange: one 1,000 loan with a 300 deposit under the Simple Method.
        Act:     generate OF 07.00.
        Assert:  0035 = 0, 0070 = -300, 0130 = 0, 0140 = 0.
        """
        frame = pl.LazyFrame(
            {
                "exposure_reference": ["FCSM"],
                "approach_applied": ["standardised"],
                "exposure_class": ["corporate"],
                "counterparty_reference": ["CP_A"],
                "drawn_amount": [1000.0],
                "undrawn_amount": [0.0],
                "scra_provision_amount": [0.0],
                "gcra_provision_amount": [0.0],
                "on_bs_netting_amount": [300.0],
                "on_bs_netting_adjusted_value": [0.0],
                "collateral_adjusted_value": [0.0],
                "collateral_market_value": [300.0],
                "fcsm_collateral_value": [300.0],
                "ead_final": [1000.0],
                "rwa_final": [700.0],
                "risk_weight": [0.7],
            }
        )
        total = _corporate_total(frame, "BASEL_3_1")
        assert total["0035"] == pytest.approx(0.0)
        assert total["0070"] == pytest.approx(-300.0)
        assert total["0130"] == pytest.approx(0.0)
        assert total["0140"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Moved from test_cross.py::TestOnBSNetting (the C 07.00 cases)
# ---------------------------------------------------------------------------


def _sa_results_with_netting() -> pl.LazyFrame:
    """SA results with on-balance-sheet netting on two obligors.

    RE-ANCHORED when col 0035's carrier changed: this frame used to set
    ``on_bs_netting_amount`` beside a ``collateral_adjusted_value`` of zero — a
    row the ledger cannot produce, since the netted deposit IS part of the
    collateral column. It now carries the adjusted value col 0035 reads, inside
    the collateral columns. Every assertion below is unchanged.
    """
    netting = [150.0, 0.0, 200.0, 0.0]
    return pl.LazyFrame(
        {
            "exposure_reference": ["SA_CORP_1", "SA_CORP_2", "SA_INST_1", "SA_RETAIL_1"],
            "approach_applied": ["standardised"] * 4,
            "exposure_class": ["corporate", "corporate", "institution", "retail_other"],
            "drawn_amount": [1000.0, 2000.0, 3000.0, 500.0],
            "undrawn_amount": [500.0, 0.0, 0.0, 100.0],
            "ead_final": [1200.0, 2000.0, 3000.0, 550.0],
            "rwa_final": [1200.0, 2000.0, 600.0, 412.5],
            "risk_weight": [1.00, 1.00, 0.20, 0.75],
            "scra_provision_amount": [10.0, 20.0, 0.0, 5.0],
            "gcra_provision_amount": [5.0, 10.0, 15.0, 2.0],
            "on_bs_netting_amount": netting,
            "on_bs_netting_adjusted_value": netting,
            "collateral_adjusted_value": netting,
            "collateral_market_value": netting,
            "guaranteed_portion": [0.0, 0.0, 0.0, 0.0],
            "sa_cqs": [3, None, 2, None],
            "counterparty_reference": ["CP_A", "CP_B", "CP_D", "CP_E"],
        }
    )


class TestOnBSNetting:
    """Task 3D: On-balance-sheet netting (COREP col 0035).

    Why: Basel 3.1 introduces col 0035 to separately report on-BS netting
    within the EAD waterfall: Original (0010) - Provisions (0030) - Netting
    (0035) = Net exposure (0040). Without this, the netting benefit is
    invisible in COREP reporting.
    """

    def test_c07_col_0035_populated_b31(self) -> None:
        """Col 0035 shows the summed netting for Basel 3.1 — negative per Annex II §1.3."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_netting(), framework="BASEL_3_1")
        corp = _get_total_row(bundle.c07_00["corporate"])
        # SA_CORP_1 has 150 netting, SA_CORP_2 has 0 → total 150; stored as negative deduction
        assert corp["0035"][0] == pytest.approx(-150.0)

    def test_c07_col_0035_absent_crr(self) -> None:
        """Col 0035 doesn't exist under CRR (no on-BS netting column)."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_netting(), framework="CRR")
        corp = _get_total_row(bundle.c07_00["corporate"])
        assert "0035" not in corp.columns

    def test_c07_col_0040_includes_netting_b31(self) -> None:
        """Col 0040 is net exposure after provisions and netting deductions."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_netting(), framework="BASEL_3_1")
        corp = _get_total_row(bundle.c07_00["corporate"])
        v_0040 = corp["0040"][0]
        # Engine: 0010=3500, 0030=-45, 0035=-150 → 0040=3305 (3500 - 45 - 150)
        assert v_0040 == pytest.approx(3305.0)

    def test_c07_zero_netting_class(self) -> None:
        """Class with no netting exposures reports 0 for col 0035."""
        gen = LedgerShimCorepGenerator()
        bundle = gen.generate_from_lazyframe(_sa_results_with_netting(), framework="BASEL_3_1")
        retail = _get_total_row(bundle.c07_00["retail"])
        assert retail["0035"][0] == pytest.approx(0.0)

    def test_c07_netting_without_column(self) -> None:
        """Without the netting carrier in data, col 0035 is None — and col 0130
        still reports the whole collateral column, as it did before the carrier
        existed (corporate + corporate SME: 100 + 0 + 50)."""
        gen = LedgerShimCorepGenerator()
        # _sa_results() carries neither netting column
        bundle = gen.generate_from_lazyframe(_sa_results(), framework="BASEL_3_1")
        corp = _get_total_row(bundle.c07_00["corporate"])
        assert corp["0035"][0] is None
        assert corp["0130"][0] == pytest.approx(-150.0)
