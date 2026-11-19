"""
Review CC-04 through the real pipeline: IR hedging sets per currency, both regimes.

Pipeline position:
    RawDataBundle -> PipelineOrchestrator -> ccr_sa_ccr stage -> SA calculator
    -> aggregated results (synthetic ``ccr__<netting_set_id>`` row)

Key responsibilities:
- One netting set holding a GBP 100m payer swap and a USD 100m receiver swap of
  the same 5-year tenor must carry the SUM of two hedging-set add-ons, under
  current UK CRR and under Basel 3.1.

Rule text: CCR (CRR) Part Art. 277a(1)(a), unchanged by PS1/26 — "transactions
mapped to the interest rate risk category shall be assigned to the same hedging
set only where their primary risk driver ... is denominated in the same
currency"; Art. 280a(1) sums the hedging-set add-ons.

Defect pinned: pre-fix the two trades were pooled into one hedging set and
offset exactly — addon_aggregate 0, ead_ccr 0 in BOTH regimes (measured).

FX note: the run's fx_rates carries USD->GBP at 1.0, so the expected numbers do
not depend on whether trade notionals are converted to the reporting currency
(review CC-05, a separate cluster). Conversion at any rate r would give
AddOn = A_GBP + r × A_USD.

Hand calculation (SA-CCR Art. 279b(1)(a): d = notional × SD, SD =
(e^(-0.05·S) - e^(-0.05·E)) / 0.05, S floored at 10/250 = 0.04y, E in
calendar days / 365.25; MF = 1 (BD >= 250); RC = 0 (MtM 0); PFE multiplier 1;
alpha 1.4 for a financial counterparty):

    CRR  2026-03-31 -> 2031-03-31, E = 1826/365.25 = 4.999316, SD = 4.383491
        AddOn per currency = 0.005 × 100m × SD = 2,191,745.621
        AddOn_IR = 2 × 2,191,745.621          = 4,383,491.243
        EAD = 1.4 × 4,383,491.243             = 6,136,887.740
    B31  2027-03-31 -> 2032-03-31, E = 1827/365.25 = 5.002053, SD = 4.385623
        AddOn per currency                    = 2,192,811.705
        AddOn_IR                              = 4,385,623.410
        EAD                                   = 6,139,872.774

References:
    - CRR Art. 277a(1)(a); Art. 279b(1)(a); Art. 280a(1); Art. 274(2)
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from rwa_calc.contracts.bundles import (
    CCRCollateralBundle,
    MarginAgreementBundle,
    NettingSetBundle,
    RawCCRBundle,
    RawDataBundle,
    TradeBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FACILITY_MAPPING_SCHEMA,
    FACILITY_SCHEMA,
    FX_RATES_SCHEMA,
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.margin_builder import create_margin_agreements
from tests.fixtures.ccr.netting_set_builder import create_netting_sets, make_netting_set
from tests.fixtures.ccr.trade_builder import create_trades, make_trade
from tests.fixtures.raw_bundle import make_raw_bundle

_NOTIONAL = 100_000_000.0

#: regime -> (reporting date, maturity date, AddOn_IR, ead_ccr) — module docstring.
_REGIMES = {
    "crr": (date(2026, 3, 31), date(2031, 3, 31), 4_383_491.243, 6_136_887.740),
    "b31": (date(2027, 3, 31), date(2032, 3, 31), 4_385_623.410, 6_139_872.774),
}


def _config(regime: str, reporting_date: date) -> CalculationConfig:
    factory = CalculationConfig.crr if regime == "crr" else CalculationConfig.basel_3_1
    return factory(reporting_date=reporting_date, permission_mode=PermissionMode.STANDARDISED)


def _bundle(reporting_date: date, maturity_date: date, currencies: list[str]) -> RawDataBundle:
    """One financial counterparty, one netting set, one 5y swap per currency.

    The first currency's swap is a payer (long), every later one a receiver (short).
    """
    counterparty = pl.DataFrame(
        [
            {
                "counterparty_reference": "CP-FIN",
                "counterparty_name": "Financial counterparty",
                "entity_type": "institution",
                "country_code": "GB",
                "default_status": False,
                "counterparty_type": "financial",
            }
        ],
        schema=dtypes_of(COUNTERPARTY_SCHEMA),
    )
    trades = create_trades(
        [
            make_trade(
                trade_id=f"T-{currency}",
                netting_set_id="NS1",
                currency=currency,
                notional=_NOTIONAL,
                is_long=index == 0,
                start_date=reporting_date,
                maturity_date=maturity_date,
            )
            for index, currency in enumerate(currencies)
        ]
    )
    netting_sets = create_netting_sets(
        [
            make_netting_set(
                netting_set_id="NS1", counterparty_reference="CP-FIN", is_legally_enforceable=True
            )
        ]
    )
    fx_rates = pl.LazyFrame(
        [{"currency_from": "USD", "currency_to": "GBP", "rate": 1.0}],
        schema=dtypes_of(FX_RATES_SCHEMA),
    )
    return make_raw_bundle(
        counterparties=counterparty.lazy(),
        facilities=pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA)),
        loans=pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA)),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        ratings=pl.LazyFrame(schema=dtypes_of(RATINGS_SCHEMA)),
        fx_rates=fx_rates,
        ccr=RawCCRBundle(
            trades=TradeBundle(trades=trades.lazy()),
            netting_sets=NettingSetBundle(netting_sets=netting_sets.lazy()),
            margin_agreements=MarginAgreementBundle(
                margin_agreements=create_margin_agreements([]).lazy()
            ),
            ccr_collateral=CCRCollateralBundle(
                ccr_collateral=pl.LazyFrame(schema=dtypes_of(CCR_COLLATERAL_SCHEMA))
            ),
        ),
    )


def _ccr_row(regime: str, currencies: list[str]) -> dict:
    reporting_date, maturity_date, _, _ = _REGIMES[regime]
    result = PipelineOrchestrator().run_with_data(
        _bundle(reporting_date, maturity_date, currencies), _config(regime, reporting_date)
    )
    rows = result.results.collect().filter(pl.col("exposure_reference") == "ccr__NS1").to_dicts()
    assert len(rows) == 1, f"expected one ccr__NS1 row, got {len(rows)}"
    return rows[0]


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_gbp_payer_and_usd_receiver_add_two_hedging_sets(regime: str) -> None:
    """GBP +100m / USD -100m in one netting set: AddOn_IR and EAD per the hand calc."""
    # Arrange
    _, _, expected_addon, expected_ead = _REGIMES[regime]

    # Act
    row = _ccr_row(regime, ["GBP", "USD"])

    # Assert
    assert row["addon_by_asset_class"]["interest_rate"] == pytest.approx(expected_addon, rel=1e-9)
    assert row["addon_aggregate"] == pytest.approx(expected_addon, rel=1e-9)
    assert row["ead_ccr"] == pytest.approx(expected_ead, rel=1e-9), (
        f"{regime}: ead_ccr {row['ead_ccr']:,.2f} vs {expected_ead:,.2f}; 0 means the two "
        "currencies were pooled into one hedging set and offset (Art. 277a(1)(a))"
    )
    assert row["rwa_final"] == pytest.approx(row["ead_final"] * row["risk_weight"], rel=1e-9)


@pytest.mark.parametrize("regime", ["crr", "b31"])
def test_two_currency_add_on_is_the_sum_of_the_single_currency_add_ons(regime: str) -> None:
    """AddOn(GBP + USD) == AddOn(GBP alone) + AddOn(USD alone): no cross-currency offset."""
    # Arrange / Act
    both = _ccr_row(regime, ["GBP", "USD"])["addon_aggregate"]
    gbp_alone = _ccr_row(regime, ["GBP"])["addon_aggregate"]
    usd_alone = _ccr_row(regime, ["USD"])["addon_aggregate"]

    # Assert
    assert gbp_alone > 0.0
    assert both == pytest.approx(gbp_alone + usd_alone, rel=1e-12)
