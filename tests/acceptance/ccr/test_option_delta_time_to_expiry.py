"""
SA-CCR option add-on through the real pipeline: the delta's T is time to expiry
from the reporting date, not the trade's original tenor — both regimes.

Pipeline position:
    RawDataBundle -> ccr_sa_ccr stage (ccr_rows_to_exposures ->
    compute_supervisory_delta_option) -> SA calculator -> results

Key responsibilities:
- Four at-the-money commodity options that differ only in their start date
  (fresh, seasoned, forward-start) or in call/put, all expiring one calendar
  year after the reporting date, each in its own netting set, take the PFE
  add-on of a one-year option — under current UK CRR and under Basel 3.1.

Rule text (PRA Rulebook, Counterparty Credit Risk (CRR) Part, Art. 279a(1)(a);
the article has no PS1/26 version, so the same text applies from 1 Jan 2027):
    "T = the period between the expiry date of the option (Texp) and the
    calculation date; for options which can be exercised at one future date
    only, Texp is equal to that date ... T shall be expressed in years using
    business days".
    Table 1: "Commodity | Other commodities (excluding electricity) | 70%".

Defect pinned (measured on the unfixed engine): T was
``(maturity_date - start_date) / 365``, so the add-ons were
    CRR  seasoned call 1,409,650.07 (T = 5.0027y, +23.0%), forward-start call
         1,075,685.76 (T = 0.4986y, -6.2%), seasoned put 390,349.93 (-40.3%),
         against 1,146,295.17 / 1,146,295.17 / 653,704.83 under the rule;
    B31  1,409,763.35 / 1,076,157.98 / 390,236.65 against 1,146,618.76 /
         1,146,618.76 / 653,381.24.
The fresh call (start = reporting date) was right before and after: the control.

Hand calculation (P = K = 100, market_price 100 x 100,000 units -> adjusted
notional d = 10,000,000 per Art. 279b(1)(c); commodity OIL_GAS SF = 18%; one
trade per hedging set, so AddOn = SF x |delta| x d x MF; MF = 1 (>= 250
business days to expiry, Art. 279c(1)); MtM 0 so RC = 0 and the PFE multiplier
is 1; financial counterparty so alpha = 1.4):
    CRR  reporting 2026-03-31, expiry 2027-03-31: T = 365 / 365 = 1.0
         d1 = 0.5 x 0.70 x sqrt(1.0) = 0.35
         call delta = N(0.35) = 0.636830651   AddOn 1,146,295.17 -> EAD 1,604,813.24
         put  delta = -N(-0.35) = -0.363169   AddOn   653,704.83 -> EAD   915,186.76
    B31  reporting 2027-03-31, expiry 2028-03-31: T = 366 / 365 = 1.002740
         d1 = 0.35 x sqrt(1.002740) = 0.350479
         call delta = N(0.350479) = 0.637010423  AddOn 1,146,618.76 -> EAD 1,605,266.27
         put  delta = -0.362989577               AddOn   653,381.24 -> EAD   914,733.73
(The test recomputes these from math.erf.)

Day-count basis: calendar days / 365 — the engine's existing basis for T; only
the origin moves. The article's "using business days" unit is a separate,
recorded residual.

References:
    - PRA CCR (CRR) Part Art. 274(2), 275(1), 278, 279a(1)(a), 279b(1)(c), 279c(1), 280
"""

from __future__ import annotations

import math
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
    LENDING_MAPPING_SCHEMA,
    LOAN_SCHEMA,
    RATINGS_SCHEMA,
)
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.margin_builder import create_margin_agreements
from tests.fixtures.ccr.netting_set_builder import create_netting_sets, make_netting_set
from tests.fixtures.ccr.trade_builder import create_trades, make_commodity_trade
from tests.fixtures.raw_bundle import make_raw_bundle

#: regime -> (reporting date, option expiry one calendar year later)
_DATES = {
    "crr": (date(2026, 3, 31), date(2027, 3, 31)),
    "b31": (date(2027, 3, 31), date(2028, 3, 31)),
}

#: leg -> (start date, option type). Every leg expires on the regime's expiry.
_LEGS = {
    "crr": {
        "fresh_call": (date(2026, 3, 31), "call"),
        "seasoned_call": (date(2022, 3, 31), "call"),
        "forward_start_call": (date(2026, 9, 30), "call"),
        "seasoned_put": (date(2022, 3, 31), "put"),
    },
    "b31": {
        "fresh_call": (date(2027, 3, 31), "call"),
        "seasoned_call": (date(2023, 3, 31), "call"),
        "forward_start_call": (date(2027, 9, 30), "call"),
        "seasoned_put": (date(2023, 3, 31), "put"),
    },
}

_ADJUSTED_NOTIONAL = 100.0 * 100_000.0  # market_price x number_of_units
_SF_OIL_GAS = 0.18  # Art. 280 table: commodity, other than electricity
_SIGMA_OTHER_COMMODITY = 0.70  # Art. 279a(1)(a) Table 1
_ALPHA = 1.4  # Art. 274(2), financial counterparty


def _phi(x: float) -> float:
    """Standard normal CDF via math.erf (independent of the engine backend)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _expected_addon(regime: str, option_type: str) -> float:
    """SF x |delta| x d with T = (expiry - reporting date) / 365, P = K."""
    reporting, expiry = _DATES[regime]
    t_years = (expiry - reporting).days / 365.0
    d1 = 0.5 * _SIGMA_OTHER_COMMODITY * math.sqrt(t_years)
    abs_delta = _phi(d1) if option_type == "call" else _phi(-d1)
    return _SF_OIL_GAS * abs_delta * _ADJUSTED_NOTIONAL


def _bundle(regime: str) -> RawDataBundle:
    _, expiry = _DATES[regime]
    legs = _LEGS[regime]
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
            make_commodity_trade(
                trade_id=leg,
                netting_set_id=leg,
                notional=_ADJUSTED_NOTIONAL,
                market_price=100.0,
                number_of_units=100_000.0,
                start_date=start,
                maturity_date=expiry,
                option_type=option_type,
                option_strike=100.0,
                option_underlying_price=100.0,
            )
            for leg, (start, option_type) in legs.items()
        ]
    )
    netting_sets = create_netting_sets(
        [
            make_netting_set(
                netting_set_id=leg, counterparty_reference="CP-FIN", is_legally_enforceable=True
            )
            for leg in legs
        ]
    )
    return make_raw_bundle(
        counterparties=counterparty.lazy(),
        facilities=pl.LazyFrame(schema=dtypes_of(FACILITY_SCHEMA)),
        loans=pl.LazyFrame(schema=dtypes_of(LOAN_SCHEMA)),
        facility_mappings=pl.LazyFrame(schema=dtypes_of(FACILITY_MAPPING_SCHEMA)),
        lending_mappings=pl.LazyFrame(schema=dtypes_of(LENDING_MAPPING_SCHEMA)),
        ratings=pl.LazyFrame(schema=dtypes_of(RATINGS_SCHEMA)),
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


@pytest.fixture(scope="module", params=["crr", "b31"])
def ccr_rows(request: pytest.FixtureRequest) -> tuple[str, dict[str, dict]]:
    """Run the four-leg option book once per regime; key the CCR rows by leg."""
    regime = request.param
    factory = CalculationConfig.crr if regime == "crr" else CalculationConfig.basel_3_1
    config = factory(reporting_date=_DATES[regime][0], permission_mode=PermissionMode.STANDARDISED)
    result = PipelineOrchestrator().run_with_data(_bundle(regime), config)
    rows = (
        result.results.collect()
        .filter(pl.col("exposure_reference").str.starts_with("ccr__"))
        .to_dicts()
    )
    return regime, {row["exposure_reference"].removeprefix("ccr__"): row for row in rows}


@pytest.mark.parametrize(
    "leg", ["fresh_call", "seasoned_call", "forward_start_call", "seasoned_put"]
)
def test_option_addon_uses_time_to_expiry_from_reporting_date(
    ccr_rows: tuple[str, dict[str, dict]], leg: str
) -> None:
    """Each leg's PFE add-on and EAD are those of a one-year option.

    Arrange: four ATM OIL_GAS options, one per netting set, each expiring one
        calendar year after the reporting date; start dates fresh / 4y seasoned /
        6m forward-start.
    Act: PipelineOrchestrator.run_with_data (CRR and Basel 3.1).
    Assert: addon_aggregate = 0.18 x |delta(T)| x 10m and ead_ccr = 1.4 x addon,
        T = (expiry - reporting date) / 365 (rel 1e-9).
    """
    # Arrange
    regime, rows = ccr_rows
    option_type = _LEGS[regime][leg][1]
    expected_addon = _expected_addon(regime, option_type)

    # Act
    row = rows[leg]

    # Assert
    assert row["addon_aggregate"] == pytest.approx(expected_addon, rel=1e-9), (
        f"{regime}/{leg}: addon {row['addon_aggregate']:,.2f} != {expected_addon:,.2f}; "
        "the option delta's T must run from the reporting date to expiry (Art. 279a(1)(a))"
    )
    assert row["ead_ccr"] == pytest.approx(_ALPHA * expected_addon, rel=1e-9)


def test_seasoned_and_forward_start_calls_match_the_fresh_call(
    ccr_rows: tuple[str, dict[str, dict]],
) -> None:
    """Same expiry, same remaining life: the start date does not move the add-on.

    Arrange / Act: the four-leg run (both regimes).
    Assert: seasoned and forward-start call add-ons equal the fresh call's
        (rel 1e-12) — the regression this item fixes, stated as a relation.
    """
    # Arrange
    _, rows = ccr_rows

    # Act
    fresh = rows["fresh_call"]["addon_aggregate"]

    # Assert
    assert rows["seasoned_call"]["addon_aggregate"] == pytest.approx(fresh, rel=1e-12)
    assert rows["forward_start_call"]["addon_aggregate"] == pytest.approx(fresh, rel=1e-12)
