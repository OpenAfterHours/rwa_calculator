"""
Unit tests for review cluster saccr_b: SA-CCR collateral valuation (CC-02), CSA
term resolution (CC-03) and reporting-currency rebasing (CC-05).

Pipeline position:
    engine/ccr: reporting_currency -> margin_terms -> collateral ->
    exposure_value (each tested here on small frames)

Key responsibilities:
- Margin terms: a netting set's terms coalesce with its agreement's; a conflict
  takes the conservative value and is a CCR025 finding; the Art. 285(3)(a) trade
  count is max(stated, counted).
- Currency: amounts convert at the row's spot rate; an unconvertible row keeps
  its amount and is exactly the CCR026 finding set.
- Collateral: the CCR024 findings are exactly the items given no value; Hfx is
  waived only for a single-currency netting set (Art. 223(2) / Art. 224 Table 4);
  segregated posted collateral is left out of NICA only (Art. 276(1)(g)).
- The Art. 272(4) split re-keys a single-trade netting set's collateral and leaves
  a multi-trade one's unattributable.

References:
- CCR (CRR) Part Art. 274(1), 275, 276(1)-(3), 279b(3); CRR Art. 197, 224, 285.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    TradeBundle,
)
from rwa_calc.contracts.config import CalculationConfig, CCRConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    MARGIN_AGREEMENT_SCHEMA,
    NETTING_SET_SCHEMA,
)
from rwa_calc.engine.ccr import apply_legal_enforceability_gate, ccr_rows_to_exposures
from rwa_calc.engine.ccr.collateral import (
    _valued_items,
    ccr_collateral_findings,
    collateral_horizons,
    value_ccr_collateral,
)
from rwa_calc.engine.ccr.margin_terms import margin_term_conflicts, resolve_margin_terms
from rwa_calc.engine.ccr.reporting_currency import (
    rebase_to_reporting_currency,
    reporting_currency_findings,
    reporting_currency_rates,
)
from tests.fixtures.ccr.netting_set_builder import create_netting_sets, make_netting_set
from tests.fixtures.ccr.trade_builder import create_trades, make_trade

_REPORTING = date(2027, 3, 31)
_MATURITY = date(2032, 3, 31)
_B31 = CalculationConfig.basel_3_1(reporting_date=_REPORTING)


# ---------------------------------------------------------------------------
# Margin terms (CC-03)
# ---------------------------------------------------------------------------


def test_netting_set_and_agreement_terms_coalesce_conservatively() -> None:
    """Stated on one side -> taken; stated on both and differing -> max TH/MTA/MPOR, min NICA."""
    # Arrange
    netting_sets = _netting_sets(
        [
            {"netting_set_id": "ONLY-MA", "margin_agreement_id": "MA1"},
            {
                "netting_set_id": "BOTH",
                "margin_agreement_id": "MA1",
                "margin_threshold": 50_000.0,
                "nica": 300_000.0,
                "mpor_days": 15,
            },
            {"netting_set_id": "NO-MA", "minimum_transfer_amount": 7.0},
        ]
    )
    agreements = _agreements(
        [
            {
                "margin_agreement_id": "MA1",
                "margin_threshold": 100_000.0,
                "minimum_transfer_amount": 20_000.0,
                "nica": 250_000.0,
                "mpor_days": 10,
            }
        ]
    )

    # Act
    terms = _by_id(resolve_margin_terms(netting_sets, agreements, _trades([])).collect())

    # Assert
    assert terms["ONLY-MA"]["margin_threshold"] == 100_000.0
    assert terms["ONLY-MA"]["nica"] == 250_000.0
    assert terms["BOTH"]["margin_threshold"] == 100_000.0  # max
    assert terms["BOTH"]["minimum_transfer_amount"] == 20_000.0
    assert terms["BOTH"]["nica"] == 250_000.0  # min of signed NICA
    assert terms["BOTH"]["mpor_days_input"] == 15  # max
    assert terms["NO-MA"]["margin_threshold"] == 0.0  # unstated TH reads as 0
    assert terms["NO-MA"]["minimum_transfer_amount"] == 7.0
    assert terms["NO-MA"]["nica"] is None  # unstated NICA stays unstated


def test_only_differing_stated_terms_are_conflicts() -> None:
    """A null on either side, or equal values, is not a CCR025 conflict."""
    # Arrange
    netting_sets = _netting_sets(
        [
            {"netting_set_id": "DIFF", "margin_agreement_id": "MA1", "margin_threshold": 1.0},
            {"netting_set_id": "SAME", "margin_agreement_id": "MA1", "margin_threshold": 2.0},
            {"netting_set_id": "NULL", "margin_agreement_id": "MA1"},
        ]
    )
    agreements = _agreements([{"margin_agreement_id": "MA1", "margin_threshold": 2.0}])

    # Act
    conflicts = margin_term_conflicts(netting_sets, agreements).collect()

    # Assert
    assert conflicts.select("netting_set_id", "term", "applied_value").rows() == [
        ("DIFF", "margin_threshold", 2.0)
    ]


def test_trade_count_floors_the_stated_number_of_trades() -> None:
    """Art. 285(3)(a): number_of_trades = max(stated, trades in the input)."""
    # Arrange
    netting_sets = _netting_sets(
        [
            {"netting_set_id": "UNDER", "number_of_trades": 1},
            {"netting_set_id": "OVER", "number_of_trades": 9},
        ]
    )
    trades = _trades(["UNDER", "UNDER", "UNDER", "OVER"])

    # Act
    terms = _by_id(resolve_margin_terms(netting_sets, _agreements([]), trades).collect())

    # Assert
    assert terms["UNDER"]["number_of_trades"] == 3
    assert terms["OVER"]["number_of_trades"] == 9


# ---------------------------------------------------------------------------
# Reporting currency (CC-05)
# ---------------------------------------------------------------------------


def test_unconvertible_rows_are_exactly_the_currency_findings() -> None:
    """Rebased: GBP x1, JPY x0.005; kept: CHF (no rate), null; FX rows kept by ``keep``."""
    # Arrange
    rates = reporting_currency_rates(
        pl.LazyFrame({"currency_from": ["JPY"], "currency_to": ["GBP"], "rate": [0.005]}), "GBP"
    )
    frame = pl.LazyFrame(
        {
            "trade_id": ["G", "J", "C", "N", "F"],
            "netting_set_id": ["NS"] * 5,
            "currency": ["GBP", "JPY", "CHF", None, "JPY"],
            "asset_class": ["interest_rate"] * 4 + ["fx"],
            "notional": [100.0, 1_000.0, 100.0, 100.0, 1_000.0],
        }
    )

    # Act
    rebased = rebase_to_reporting_currency(
        frame, ("notional",), rates, keep=pl.col("asset_class") == "fx"
    ).collect()
    findings = reporting_currency_findings({"ccr.trades|trade_id": frame}, rates)

    # Assert
    assert dict(zip(rebased["trade_id"], rebased["notional"], strict=True)) == {
        "G": 100.0,
        "J": 5.0,
        "C": 100.0,
        "N": 100.0,
        "F": 1_000.0,
    }
    assert findings is not None
    assert sorted(findings.collect()["record_id"].to_list()) == ["C", "N"]


# ---------------------------------------------------------------------------
# Collateral (CC-02)
# ---------------------------------------------------------------------------


def test_collateral_findings_are_exactly_the_items_given_no_value() -> None:
    """CCR024 flags precisely the items whose signed value is zero (Art. 197 gate)."""
    # Arrange
    items = [
        _item("CASH", "cash"),
        _item("GOVT-1", "govt_bond", issuer_cqs=1, residual_maturity_years=3.0),
        _item("CORP-4", "corp_bond", issuer_cqs=4, residual_maturity_years=3.0),
        _item("EQ-MAIN", "equity", is_main_index=True),
        _item("EQ-OTHER", "equity", is_main_index=False),
        _item("RE", "real_estate"),
        _item("CLN", "credit_linked_note"),
        _item("GOLD", "gold"),
    ]
    collateral = _collateral(items)
    netting_sets = pl.LazyFrame({"netting_set_id": ["NS1"], "is_margined": [False]})

    # Act
    findings = ccr_collateral_findings(
        collateral, netting_sets, netting_sets.select("netting_set_id"), _B31
    ).collect()
    valued = (
        _valued_items(collateral, _horizons(netting_sets), None, _B31, None)
        .filter(pl.col("_basis") == "unmargined")
        .collect()
    )

    # Assert
    zero_valued = set(valued.filter(pl.col("_signed_value") == 0.0)["ccr_collateral_reference"])
    assert set(findings["ccr_collateral_reference"]) == zero_valued
    assert zero_valued == {"CORP-4", "EQ-OTHER", "RE", "CLN"}


@pytest.mark.parametrize(
    ("trade_currencies", "expected_value"),
    [
        # Single-currency GBP netting set: Hfx waived; cash HC 0 -> full value.
        (["GBP"], 1_000_000.0),
        # GBP + USD trades: no single settlement currency -> Hfx at the one-year
        # horizon: 8% x sqrt(250 / 10) = 40% -> 600,000.
        (["GBP", "USD"], 600_000.0),
    ],
)
def test_currency_mismatch_haircut_waived_only_for_a_single_currency_set(
    trade_currencies: list[str], expected_value: float
) -> None:
    """Art. 223(2) / Art. 224 Table 4 Hfx on received GBP cash, unmargined 5y set."""
    # Arrange
    trades = (
        _trades(["NS1"] * len(trade_currencies))
        .with_columns(pl.Series("currency", trade_currencies))
        .with_columns(
            pl.lit(None, dtype=pl.String).alias("currency_leg2"),
            pl.lit(1_000, dtype=pl.Int32).alias("business_days_to_maturity"),
        )
    )
    netting_sets = resolve_margin_terms(
        _netting_sets([{"netting_set_id": "NS1"}]), _agreements([]), trades
    )
    horizons = collateral_horizons(netting_sets, trades, pl.lit(10))

    # Act
    out = value_ccr_collateral(
        _collateral([_item("CASH", "cash", currency="GBP")]), horizons, None, _B31
    ).collect()

    # Assert
    assert out["collateral_unmargined"][0] == pytest.approx(expected_value, rel=1e-12)


def test_segregated_posted_item_leaves_nica_but_stays_in_variation_margin() -> None:
    """Art. 276(1)(g) excludes it from NICA only; posted VM keeps its negative sign."""
    # Arrange
    items = [
        _item("VM-SEG", "cash", posted=True, segregated=True, role="vm"),
        _item("IM-SEG", "cash", posted=True, segregated=True, role="im"),
        _item("IM", "cash", posted=True, role="im"),
    ]
    netting_sets = pl.LazyFrame(
        {
            "netting_set_id": ["NS1"],
            "is_margined": [True],
            "_horizon_margined": [10],
            "_horizon_unmargined": [250],
            "_ns_currency": ["GBP"],
        }
    )

    # Act
    out = value_ccr_collateral(_collateral(items), netting_sets, None, _B31).collect()

    # Assert
    assert out["vm_net"][0] == pytest.approx(-1_000_000.0)
    assert out["nica_collateral"][0] == pytest.approx(-1_000_000.0)
    assert out["collateral_unmargined"][0] == pytest.approx(-1_000_000.0)


def test_enforceability_split_rekeys_single_trade_collateral_only() -> None:
    """Art. 274(1): a one-trade set's collateral follows it; a two-trade set's cannot."""
    # Arrange
    raw = RawCCRBundle(
        trades=TradeBundle(trades=_trades(["ONE", "TWO", "TWO"])),
        netting_sets=NettingSetBundle(
            netting_sets=create_netting_sets(
                [
                    make_netting_set(netting_set_id=ns, is_legally_enforceable=False)
                    for ns in ("ONE", "TWO")
                ]
            ).lazy()
        ),
        margin_agreements=MarginAgreementBundle(margin_agreements=_agreements([])),
        ccr_collateral=CCRCollateralBundle(
            ccr_collateral=_collateral(
                [
                    _item("C-ONE", "cash", netting_set_id="ONE"),
                    _item("C-TWO", "cash", netting_set_id="TWO"),
                ]
            )
        ),
    )

    # Act
    gated = apply_legal_enforceability_gate(raw)
    findings = ccr_collateral_findings(
        gated.ccr_collateral.ccr_collateral,
        gated.netting_sets.netting_sets,
        raw.netting_sets.netting_sets.select("netting_set_id"),
        _B31,
    ).collect()

    # Assert
    keyed = dict(
        gated.ccr_collateral.ccr_collateral.select("ccr_collateral_reference", "netting_set_id")
        .collect()
        .rows()
    )
    assert keyed == {"C-ONE": "ONE__split__T-0", "C-TWO": "TWO"}
    assert findings.select("ccr_collateral_reference", "reason").rows() == [
        ("C-TWO", "not_attributable")
    ]


def test_direct_caller_values_collateral_without_a_config() -> None:
    """ccr_rows_to_exposures without a run config uses the regime default haircuts."""
    # Arrange
    raw = RawCCRBundle(
        trades=TradeBundle(
            trades=_trades(["NS1"]).with_columns(pl.lit(2_000_000.0).alias("mtm_value"))
        ),
        netting_sets=NettingSetBundle(
            netting_sets=create_netting_sets([make_netting_set(netting_set_id="NS1")]).lazy()
        ),
        margin_agreements=MarginAgreementBundle(margin_agreements=_agreements([])),
        ccr_collateral=CCRCollateralBundle(
            ccr_collateral=_collateral([_item("CASH", "cash", market_value=1_500_000.0)])
        ),
    )

    # Act
    row = ccr_rows_to_exposures(raw, CCRConfig(), _REPORTING, is_basel_3_1=True).collect()

    # Assert
    assert row["rc"][0] == pytest.approx(500_000.0)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _item(
    reference: str,
    collateral_type: str,
    *,
    netting_set_id: str = "NS1",
    market_value: float = 1_000_000.0,
    posted: bool = False,
    segregated: bool = False,
    role: str | None = None,
    currency: str = "GBP",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "ccr_collateral_reference": reference,
        "netting_set_id": netting_set_id,
        "collateral_type": collateral_type,
        "market_value": market_value,
        "is_posted_by_firm": posted,
        "is_segregated": segregated,
        "collateral_role": role,
        "currency": currency,
        **extra,
    }


def _collateral(items: list[dict[str, Any]]) -> pl.LazyFrame:
    return pl.DataFrame(items, schema=dtypes_of(CCR_COLLATERAL_SCHEMA)).lazy()


def _horizons(netting_sets: pl.LazyFrame) -> pl.LazyFrame:
    """10-BD liquidation periods: every eligible item keeps a positive value."""
    return netting_sets.with_columns(
        pl.lit(10).alias("_horizon_margined"),
        pl.lit(10).alias("_horizon_unmargined"),
        pl.lit("GBP").alias("_ns_currency"),
    )


def _netting_sets(rows: list[dict[str, Any]]) -> pl.LazyFrame:
    return pl.DataFrame(
        [{"counterparty_reference": "CP", **row} for row in rows],
        schema=dtypes_of(NETTING_SET_SCHEMA),
    ).lazy()


def _agreements(rows: list[dict[str, Any]]) -> pl.LazyFrame:
    return pl.DataFrame(
        [{"counterparty_reference": "CP", **row} for row in rows],
        schema=dtypes_of(MARGIN_AGREEMENT_SCHEMA),
    ).lazy()


def _trades(netting_set_ids: list[str]) -> pl.LazyFrame:
    return create_trades(
        [
            make_trade(
                trade_id=f"T-{index}",
                netting_set_id=ns_id,
                notional=10_000_000.0,
                start_date=_REPORTING,
                maturity_date=_MATURITY,
            )
            for index, ns_id in enumerate(netting_set_ids)
        ]
    ).lazy()


def _by_id(frame: pl.DataFrame) -> dict[str, dict[str, Any]]:
    return {row["netting_set_id"]: row for row in frame.to_dicts()}
