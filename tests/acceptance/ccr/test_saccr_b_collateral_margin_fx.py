"""
Review cluster saccr_b through the real pipeline, both regimes: SA-CCR collateral
(CC-02), margin-agreement terms and the Art. 274(3) cap (CC-03), and the
reporting-currency conversion of CCR and SFT amounts (CC-05).

Pipeline position:
    RawDataBundle -> PipelineOrchestrator -> ccr_sa_ccr / sft_fccm stages ->
    SA calculator -> aggregated results (synthetic ``ccr__<netting_set_id>`` row)

Key responsibilities:
- Pin each hand-calculated exposure value below under current UK CRR and under
  Basel 3.1. The SA-CCR articles are unamended by PS1/26 (Annex R changes only
  Art. 273(3)(b), 274(2), 274(2A), 274(2B), 299A, 306(4), 308(3), 309(2)), so the
  two regimes differ only through the Art. 224 haircut table and the dates.
- Pin the defect each case closes: the pre-fix value is recorded per case.

Rule text (CCR (CRR) Part, in force to 31 Dec 2026 and carried into PS1/26):
- Art. 275(1): "RC = max{CMV - NICA, 0}"; 275(2): "RC = max{CMV - VM - NICA,
  TH + MTA - NICA, 0}"; 275(3): "RC = max{Σ_i max{CMV_i, 0} - max{VM_MA +
  NICA_MA, 0}, 0} + max{Σ_i min{CMV_i, 0} - min{VM_MA + NICA_MA, 0}, 0}".
- Art. 276(1): "(c) collateral received from a counterparty shall be recognised
  with a positive sign and collateral posted to a counterparty shall be
  recognised with a negative sign; (d) the volatility-adjusted value ... shall be
  calculated in accordance with Article 223 ...; (g) any collateral posted to the
  counterparty that is segregated ... bankruptcy remote ... shall not be
  recognised in the calculation of NICA". 276(2): "C VA = C · (1 + H C + H fx)"
  for collateral posted. 276(3): liquidation period "(a) the longest remaining
  maturity of transactions in the netting set, capped at OneBusinessYear ... ;
  (b) the margin period of risk ... for ... Article 275(2) and (3)".
- Art. 274(3): "The exposure value of a netting set that is subject to a
  contractual margin agreement shall be capped at the exposure value of the same
  netting set not subject to any form of margin agreement."
- Art. 278(2): the PFE of netting sets under one margin agreement is the sum of
  their PFEs "as if they were not subject to any form of a margin agreement";
  278(3): multiplier 1 if z >= 0, else min{1, 0.05 + 0.95 · exp(z / (2 · 0.95 ·
  AggAddOn))}, z = CMV - NICA (275(1)), CMV - VM - NICA (275(2)), CMV_i - NICA_i
  (275(3)).
- Art. 279b(3): "Institutions shall convert the adjusted notional amount of a
  transaction into their reporting currency at the prevailing spot exchange rate
  where the adjusted notional amount is calculated ... from a contractual
  notional amount or a market price ... denominated in another currency."

Hand calculation (every case: one financial counterparty, alpha 1.4; a long GBP
10m 5-year interest-rate swap per netting set unless stated; Art. 279b(1)(a)
SD = (e^(-0.05·0.04) - e^(-0.05·E)) / 0.05 with E in calendar days / 365.25;
unmargined MF 1; margined MF 1.5 · sqrt(10 / 250) = 0.3 at the 10-BD MPOR):

    CRR 2026-03-31 -> 2031-03-31: SD 4.383491243, AddOn 219,174.562136
    B31 2027-03-31 -> 2032-03-31: SD 4.385623410, AddOn 219,281.170504

    CC-02 posted 1.5m cash, CMV -1m: C = -1.5m, z = +0.5m, RC 0.5m, mult 1
        EAD = 1.4 · (500,000 + AddOn)    CRR 1,006,844.387  B31 1,006,993.639
        pre-fix (C ignored): RC 0, mult 0.1361, EAD 41,750.91 / 41,802.08
    CC-02 received 1.5m cash, CMV +2m: same z, same EAD (pre-fix RC 2m)
    CC-02 posted 1.5m cash segregated: not in NICA (276(1)(g)), EAD as no
        collateral at CMV -1m: 41,750.908 / 41,802.081
    CC-02 margined, received main-index equity VM 1m, CMV 1m, TH = MTA = 0:
        H_equity main index CRR 15% / B31 20% at the 10-BD MPOR (Art. 224)
        VM 850,000 / 800,000; RC_m 150,000 / 200,000; z >= 0
        EV_m = 1.4 · (RC_m + 0.3 · AddOn)    CRR 302,053.316  B31 372,098.092
        unmargined basis (cap): one-business-year horizon, H x 5 -> 75% / 100%
        EV_u 1,356,844.387 / 1,706,993.639 -> the margined value stands
    CC-03 terms on the margin agreement only (TH 10m, MTA 0.5m), CMV 1m:
        EV_m = 1.4 · (10.5m + 0.3 · AddOn) = 14,792,053.32 / 14,792,098.09
        EV_u = 1.4 · (1m + AddOn) = 1,706,844.387 / 1,706,993.639  <- cap
        pre-fix (agreement terms unread, no cap): 1,492,053.32 / 1,492,098.09
    CC-03 TH 100k on the agreement only, CMV 0:
        EV_m = 1.4 · (100,000 + 0.3 · AddOn) = 232,053.316 / 232,098.092
        EV_u = 1.4 · AddOn = 306,844.387 / 306,993.639 -> margined stands
        pre-fix (TH unread): 1.4 · 0.3 · AddOn = 92,053.316 / 92,098.092
    CC-03 two netting sets under one margin agreement (Art. 275(3)): NS-A CMV
        +2m, NS-B CMV -2m, VM 2m cash received (itemised on NS-B):
        RC_MA = max(2m - 2m, 0) + max(-2m - 0, 0) = 0
        PFE_A = AddOn (z = +2m), PFE_B = mult(-2m) · AddOn (VM is not NICA_i)
        EV_A = 1.4 · AddOn = 306,844.387 / 306,993.639
        EV_B = 17,734.719 / 17,748.941
        pre-fix (no shared RC, VM ignored): NS-A 1.4 · (2m + 0.3 · AddOn)
    CC-05 JPY 10bn swap at JPY->GBP 0.005 == GBP 50m swap:
        EAD = 1.4 · 0.005 · 50m · SD = 1,534,221.935 / 1,534,968.194
    CC-05 SFT USD 100m cash lent at USD->GBP 0.8, no collateral: E* = 80m
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
    RawDataBundle,
    RawSFTBundle,
    SftTradeBundle,
    TradeBundle,
)
from rwa_calc.contracts.config import CalculationConfig
from rwa_calc.contracts.edges import SFT_TABLE_EDGES, seal_lenient
from rwa_calc.data.column_spec import dtypes_of
from rwa_calc.data.schemas import (
    CCR_COLLATERAL_SCHEMA,
    COUNTERPARTY_SCHEMA,
    FX_RATES_SCHEMA,
    MARGIN_AGREEMENT_SCHEMA,
    SFT_TRADE_SCHEMA,
)
from rwa_calc.domain.enums import PermissionMode
from rwa_calc.engine.pipeline import PipelineOrchestrator
from tests.fixtures.ccr.netting_set_builder import create_netting_sets, make_netting_set
from tests.fixtures.ccr.trade_builder import create_trades, make_trade
from tests.fixtures.raw_bundle import make_raw_bundle

#: regime -> (reporting date, maturity date) of the 5-year swaps.
_DATES = {
    "crr": (date(2026, 3, 31), date(2031, 3, 31)),
    "b31": (date(2027, 3, 31), date(2032, 3, 31)),
}

#: Expected values per regime, from the module docstring's hand calculation.
_EXPECTED: dict[str, dict[str, float]] = {
    "crr": {
        "cash_z_half_million": 1_006_844.386989891,
        "no_collateral_cmv_minus_1m": 41_750.908383644826,
        "margined_equity_vm": 302_053.31609696726,
        "agreement_terms_capped": 1_706_844.3869898908,
        "agreement_th_100k": 232_053.3160969673,
        "shared_a": 306_844.386989891,
        "shared_b": 17_734.719076504476,
        "gbp_50m": 1_534_221.9349494553,
    },
    "b31": {
        "cash_z_half_million": 1_006_993.6387056451,
        "no_collateral_cmv_minus_1m": 41_802.08077596011,
        "margined_equity_vm": 372_098.0916116935,
        "agreement_terms_capped": 1_706_993.638705645,
        "agreement_th_100k": 232_098.09161169353,
        "shared_a": 306_993.63870564516,
        "shared_b": 17_748.94099134168,
        "gbp_50m": 1_534_968.193528226,
    },
}

_REGIMES = ["crr", "b31"]


# ---------------------------------------------------------------------------
# CC-02 — CCR collateral
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", _REGIMES)
def test_posted_cash_collateral_raises_replacement_cost(regime: str) -> None:
    """Posted 1.5m cash, CMV -1m: C = -1.5m, RC = 0.5m (pre-fix 41,8xx — 24x under)."""
    # Arrange
    collateral = [_collateral("C1", "NS1", "cash", 1_500_000.0, posted=True)]

    # Act
    row = _ccr_row(_run(regime, mtm=-1_000_000.0, collateral=collateral), "NS1")

    # Assert
    assert row["rc"] == pytest.approx(500_000.0, rel=1e-12)
    assert row["pfe_multiplier"] == pytest.approx(1.0)
    assert row["ead_ccr"] == pytest.approx(_EXPECTED[regime]["cash_z_half_million"], rel=1e-9)


@pytest.mark.parametrize("regime", _REGIMES)
def test_received_cash_collateral_reduces_replacement_cost(regime: str) -> None:
    """Received 1.5m cash, CMV +2m: RC = 0.5m (pre-fix RC = 2m, EAD 3.107m)."""
    # Arrange
    collateral = [_collateral("C1", "NS1", "cash", 1_500_000.0)]

    # Act
    row = _ccr_row(_run(regime, mtm=2_000_000.0, collateral=collateral), "NS1")

    # Assert
    assert row["rc"] == pytest.approx(500_000.0, rel=1e-12)
    assert row["ead_ccr"] == pytest.approx(_EXPECTED[regime]["cash_z_half_million"], rel=1e-9)


@pytest.mark.parametrize("regime", _REGIMES)
def test_segregated_posted_collateral_is_not_nica(regime: str) -> None:
    """Art. 276(1)(g): segregated posted cash is left out — EAD as with no collateral.

    Green before the fix too (all collateral was ignored then); it guards the
    exclusion: counting the item would give the posted-cash EAD 1.007m.
    """
    # Arrange
    collateral = [_collateral("C1", "NS1", "cash", 1_500_000.0, posted=True, segregated=True)]

    # Act
    with_item = _ccr_row(_run(regime, mtm=-1_000_000.0, collateral=collateral), "NS1")
    without = _ccr_row(_run(regime, mtm=-1_000_000.0), "NS1")

    # Assert
    assert with_item["ead_ccr"] == pytest.approx(
        _EXPECTED[regime]["no_collateral_cmv_minus_1m"], rel=1e-9
    )
    assert without["ead_ccr"] == pytest.approx(with_item["ead_ccr"], rel=1e-12)


@pytest.mark.parametrize("regime", _REGIMES)
def test_margined_equity_variation_margin_takes_the_regime_haircut(regime: str) -> None:
    """Main-index equity VM: CRR 15% / B31 20% at the MPOR; the margined EV stands."""
    # Arrange
    collateral = [_collateral("C1", "NS1", "equity", 1_000_000.0, is_main_index=True)]

    # Act
    row = _ccr_row(
        _run(regime, mtm=1_000_000.0, collateral=collateral, ns_overrides={"is_margined": True}),
        "NS1",
    )

    # Assert
    expected_rc = 150_000.0 if regime == "crr" else 200_000.0
    assert row["rc_margined"] == pytest.approx(expected_rc, rel=1e-9)
    assert row["rc"] == pytest.approx(expected_rc, rel=1e-9)
    assert row["ead_ccr"] == pytest.approx(_EXPECTED[regime]["margined_equity_vm"], rel=1e-9)


@pytest.mark.parametrize("regime", _REGIMES)
def test_ineligible_collateral_gets_no_relief_and_is_reported(regime: str) -> None:
    """Real estate is not Art. 197 collateral: no relief, CCR024 names the item."""
    # Arrange
    collateral = [_collateral("C-RE", "NS1", "real_estate", 1_500_000.0)]

    # Act
    result = _run(regime, mtm=2_000_000.0, collateral=collateral)
    row = _ccr_row(result, "NS1")

    # Assert
    assert row["rc"] == pytest.approx(2_000_000.0, rel=1e-12)
    flagged = [e for e in result.errors if e.code == "CCR024"]
    assert len(flagged) == 1
    assert "C-RE" in flagged[0].message


# ---------------------------------------------------------------------------
# CC-03 — margin-agreement terms, the Art. 274(3) cap, shared agreements
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", _REGIMES)
def test_terms_on_the_margin_agreement_are_read_and_capped(regime: str) -> None:
    """TH 10m / MTA 0.5m stated on the CSA only: EV capped at the unmargined 1.707m."""
    # Arrange
    agreement = {"margin_threshold": 10_000_000.0, "minimum_transfer_amount": 500_000.0}

    # Act
    row = _ccr_row(_run(regime, mtm=1_000_000.0, agreement=agreement), "NS1")

    # Assert
    assert row["rc_margined"] == pytest.approx(10_500_000.0, rel=1e-12), (
        "the CSA's TH + MTA must reach the Art. 275(2) floor term"
    )
    assert row["ead_ccr"] == pytest.approx(_EXPECTED[regime]["agreement_terms_capped"], rel=1e-9)
    assert row["rc"] == pytest.approx(row["rc_unmargined"], rel=1e-12)


@pytest.mark.parametrize("regime", _REGIMES)
def test_agreement_threshold_binds_below_the_cap(regime: str) -> None:
    """TH 100k on the CSA only, CMV 0: margined EV 232k (pre-fix 92k, TH unread)."""
    # Arrange
    agreement = {"margin_threshold": 100_000.0}

    # Act
    row = _ccr_row(_run(regime, mtm=0.0, agreement=agreement), "NS1")

    # Assert
    assert row["rc"] == pytest.approx(100_000.0, rel=1e-12)
    assert row["ead_ccr"] == pytest.approx(_EXPECTED[regime]["agreement_th_100k"], rel=1e-9)


@pytest.mark.parametrize("regime", _REGIMES)
def test_conflicting_threshold_takes_the_larger_and_warns(regime: str) -> None:
    """NS TH 50k vs CSA TH 100k: the conservative 100k applies; CCR025 names both."""
    # Arrange
    agreement = {"margin_threshold": 100_000.0}

    # Act
    result = _run(regime, mtm=0.0, agreement=agreement, ns_overrides={"margin_threshold": 50_000.0})
    row = _ccr_row(result, "NS1")

    # Assert
    assert row["ead_ccr"] == pytest.approx(_EXPECTED[regime]["agreement_th_100k"], rel=1e-9)
    conflicts = [e for e in result.errors if e.code == "CCR025"]
    assert len(conflicts) == 1
    assert conflicts[0].field_name == "margin_threshold"


@pytest.mark.parametrize("regime", _REGIMES)
def test_netting_sets_sharing_an_agreement_take_one_replacement_cost(regime: str) -> None:
    """Art. 275(3): +2m / -2m under one CSA with 2m VM received -> RC_MA = 0."""
    # Arrange
    collateral = [_collateral("VM-B", "NS-B", "cash", 2_000_000.0)]

    # Act
    result = _run(
        regime,
        mtm=0.0,
        collateral=collateral,
        agreement={},
        netting_sets=[("NS-A", 2_000_000.0), ("NS-B", -2_000_000.0)],
    )
    row_a = _ccr_row(result, "NS-A")
    row_b = _ccr_row(result, "NS-B")

    # Assert
    assert row_a["rc"] == pytest.approx(0.0, abs=1e-6)
    assert row_b["rc"] == pytest.approx(0.0, abs=1e-6)
    assert row_a["ead_ccr"] == pytest.approx(_EXPECTED[regime]["shared_a"], rel=1e-9)
    assert row_b["ead_ccr"] == pytest.approx(_EXPECTED[regime]["shared_b"], rel=1e-9)


# ---------------------------------------------------------------------------
# CC-05 — reporting currency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("regime", _REGIMES)
def test_foreign_currency_swap_is_converted_to_the_reporting_currency(regime: str) -> None:
    """JPY 10bn at JPY->GBP 0.005 prices as the GBP 50m swap (pre-fix 200x)."""
    # Arrange
    fx = [("JPY", 0.005)]

    # Act
    jpy = _ccr_row(_run(regime, notional=10_000_000_000.0, currency="JPY", fx=fx), "NS1")
    gbp = _ccr_row(_run(regime, notional=50_000_000.0), "NS1")

    # Assert
    assert jpy["ead_ccr"] == pytest.approx(_EXPECTED[regime]["gbp_50m"], rel=1e-9)
    assert gbp["ead_ccr"] == pytest.approx(jpy["ead_ccr"], rel=1e-12)
    assert jpy["currency"] == "GBP"
    assert jpy["original_currency"] == "JPY"


@pytest.mark.parametrize("regime", _REGIMES)
def test_foreign_currency_mtm_is_converted_before_netting(regime: str) -> None:
    """A JPY 200m MtM at 0.005 is CMV 1m GBP: RC 1m (pre-fix RC 200m)."""
    # Act
    row = _ccr_row(_run(regime, mtm=200_000_000.0, currency="JPY", fx=[("JPY", 0.005)]), "NS1")

    # Assert
    assert row["rc"] == pytest.approx(1_000_000.0, rel=1e-12)


@pytest.mark.parametrize("regime", _REGIMES)
def test_missing_rate_is_reported_and_left_unconverted(regime: str) -> None:
    """No CHF rate: CCR026 ERROR, the amount is used as it stands."""
    # Act
    result = _run(regime, notional=50_000_000.0, currency="CHF", fx=[("JPY", 0.005)])
    row = _ccr_row(result, "NS1")

    # Assert
    assert row["ead_ccr"] == pytest.approx(_EXPECTED[regime]["gbp_50m"], rel=1e-9)
    assert row["currency"] == "CHF"
    missing = [e for e in result.errors if e.code == "CCR026"]
    assert len(missing) == 1
    assert missing[0].actual_value == "'CHF'"


@pytest.mark.parametrize("regime", _REGIMES)
def test_sft_amounts_are_converted_to_the_reporting_currency(regime: str) -> None:
    """USD 100m cash lent at USD->GBP 0.8, no collateral: E* = 80m GBP (pre-fix 100m USD)."""
    # Act
    result = _run_sft(regime)
    row = result.results.collect().filter(pl.col("exposure_reference") == "ccr__SFT-NS1")

    # Assert
    assert row.height == 1
    assert row["ead_final"][0] == pytest.approx(80_000_000.0, rel=1e-12)
    assert row["currency"][0] == "GBP"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _collateral(
    reference: str,
    netting_set_id: str,
    collateral_type: str,
    market_value: float,
    *,
    posted: bool = False,
    segregated: bool = False,
    is_main_index: bool | None = None,
    currency: str = "GBP",
) -> dict[str, Any]:
    return {
        "ccr_collateral_reference": reference,
        "netting_set_id": netting_set_id,
        "collateral_type": collateral_type,
        "market_value": market_value,
        "is_posted_by_firm": posted,
        "is_segregated": segregated,
        "is_main_index": is_main_index,
        "currency": currency,
    }


def _config(regime: str) -> CalculationConfig:
    factory = CalculationConfig.crr if regime == "crr" else CalculationConfig.basel_3_1
    return factory(reporting_date=_DATES[regime][0], permission_mode=PermissionMode.STANDARDISED)


def _counterparty() -> pl.LazyFrame:
    return pl.DataFrame(
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
    ).lazy()


def _fx_rates(fx: list[tuple[str, float]]) -> pl.LazyFrame:
    return pl.LazyFrame(
        [{"currency_from": ccy, "currency_to": "GBP", "rate": rate} for ccy, rate in fx],
        schema=dtypes_of(FX_RATES_SCHEMA),
    )


def _run(
    regime: str,
    *,
    mtm: float = 0.0,
    notional: float = 10_000_000.0,
    currency: str = "GBP",
    collateral: list[dict[str, Any]] | None = None,
    agreement: dict[str, Any] | None = None,
    ns_overrides: dict[str, Any] | None = None,
    netting_sets: list[tuple[str, float]] | None = None,
    fx: list[tuple[str, float]] | None = None,
) -> Any:
    """One counterparty; one 5y swap per netting set; optional CSA covering all of them."""
    reporting_date, maturity_date = _DATES[regime]
    sets = netting_sets or [("NS1", mtm)]
    trades = create_trades(
        [
            make_trade(
                trade_id=f"T-{ns_id}",
                netting_set_id=ns_id,
                currency=currency,
                notional=notional,
                mtm_value=ns_mtm,
                start_date=reporting_date,
                maturity_date=maturity_date,
            )
            for ns_id, ns_mtm in sets
        ]
    )
    margined = {"is_margined": True, "margin_agreement_id": "MA1"} if agreement is not None else {}
    ns_frame = create_netting_sets(
        [
            make_netting_set(
                netting_set_id=ns_id,
                counterparty_reference="CP-FIN",
                is_legally_enforceable=True,
                **{**margined, **(ns_overrides or {})},
            )
            for ns_id, _ in sets
        ]
    )
    agreements = pl.DataFrame(
        [{"margin_agreement_id": "MA1", "counterparty_reference": "CP-FIN", **agreement}]
        if agreement is not None
        else [],
        schema=dtypes_of(MARGIN_AGREEMENT_SCHEMA),
    )
    collateral_frame = pl.DataFrame(collateral or [], schema=dtypes_of(CCR_COLLATERAL_SCHEMA))
    bundle = make_raw_bundle(
        counterparties=_counterparty(),
        fx_rates=_fx_rates(fx or []),
        ccr=RawCCRBundle(
            trades=TradeBundle(trades=trades.lazy()),
            netting_sets=NettingSetBundle(netting_sets=ns_frame.lazy()),
            margin_agreements=MarginAgreementBundle(margin_agreements=agreements.lazy()),
            ccr_collateral=CCRCollateralBundle(ccr_collateral=collateral_frame.lazy()),
        ),
    )
    return PipelineOrchestrator().run_with_data(bundle, _config(regime))


def _run_sft(regime: str) -> Any:
    """One USD 100m cash-lent SFT to the financial counterparty, USD->GBP 0.8."""
    reporting_date, _ = _DATES[regime]
    trade = pl.DataFrame(
        [
            {
                "trade_id": "SFT-1",
                "netting_set_id": "SFT-NS1",
                "counterparty_reference": "CP-FIN",
                "notional": 100_000_000.0,
                "currency": "USD",
                "maturity_date": date(reporting_date.year, 6, 30),
                "start_date": reporting_date,
            }
        ],
        schema=dtypes_of(SFT_TRADE_SCHEMA),
    )
    sealed, _missing, _lossy = seal_lenient(trade.lazy(), SFT_TABLE_EDGES["sft_trades"])
    bundle: RawDataBundle = make_raw_bundle(
        counterparties=_counterparty(),
        fx_rates=_fx_rates([("USD", 0.8)]),
        sft=RawSFTBundle(trades=SftTradeBundle(sft_trades=sealed)),
    )
    return PipelineOrchestrator().run_with_data(bundle, _config(regime))


def _ccr_row(result: Any, netting_set_id: str) -> dict[str, Any]:
    rows = (
        result.results.collect()
        .filter(pl.col("exposure_reference") == f"ccr__{netting_set_id}")
        .to_dicts()
    )
    assert len(rows) == 1, f"expected one ccr__{netting_set_id} row, got {len(rows)}"
    return rows[0]
