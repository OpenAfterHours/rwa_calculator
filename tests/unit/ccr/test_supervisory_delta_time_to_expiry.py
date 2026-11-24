"""
Unit tests: the SA-CCR option supervisory delta measures T from the reporting date.

Pipeline position:
    pipeline_adapter.ccr_rows_to_exposures -> compute_supervisory_delta_option

Key responsibilities:
- T in the Black-Scholes delta runs from the calculation (reporting) date to the
  option's expiry, never from the trade's start date: a seasoned option
  (start before the reporting date) and a forward-start option (start after it)
  take the same delta as a freshly-struck one with the same remaining life.
- An option at expiry (T = 0) or past it never yields a NaN delta: it takes the
  limit of the formula as T falls to zero.

Rule text (PRA Rulebook, Counterparty Credit Risk (CRR) Part, Art. 279a(1)(a);
unchanged by PS1/26 — the rulebook carries no 01/01/2027 version of the article):
    delta = sign * N(type * (ln((P + lambda)/(K + lambda)) + 0.5 * sigma^2 * T)
                     / (sigma * sqrt(T)))
    "T = the period between the expiry date of the option (Texp) and the
    calculation date; for options which can be exercised at one future date
    only, Texp is equal to that date ... T shall be expressed in years using
    business days".
    Table 1: "Equity | Multiple names instrument | 75%".

Defect pinned (measured on the unfixed engine): T was
``(maturity_date - start_date) / 365`` — the original tenor. The seasoned OTM
call below (5y original tenor, 1y left) took delta 0.782875 instead of 0.597902;
the forward-start call (6 months between start and expiry, 1y to expiry) took
0.534771. An at-the-money option at T = 0 measured from the reporting date
would be NaN under the plain formula (0 / 0).

Day-count basis: calendar days / 365, the basis the engine already used for T
(only the origin moves here). The article's "using business days" unit is a
separate, recorded residual.

Expected values are computed here from ``math.erf`` — independent of the
engine's ``normal_cdf`` backend.
"""

from __future__ import annotations

import math
from datetime import date

import polars as pl
import pytest

from rwa_calc.engine.ccr.supervisory_delta import compute_supervisory_delta_option
from tests.fixtures.ccr.trade_builder import Trade, create_trades, make_trade

_REPORTING_DATE = date(2026, 1, 15)
_EXPIRY_1Y = date(2027, 1, 15)  # 365 calendar days after the reporting date
_SIGMA_EQUITY_INDEX = 0.75  # Art. 279a(1)(a) Table 1, equity multiple names


def _phi(x: float) -> float:
    """Standard normal CDF via math.erf (independent of the engine backend)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_delta(p: float, k: float, t_years: float, *, call: bool, long: bool) -> float:
    """Art. 279a(1)(a) delta with lambda = 0: sign * N(type * d1)."""
    d1 = (math.log(p / k) + 0.5 * _SIGMA_EQUITY_INDEX**2 * t_years) / (
        _SIGMA_EQUITY_INDEX * math.sqrt(t_years)
    )
    option_type = 1.0 if call else -1.0
    sign = 1.0 if call == long else -1.0
    return sign * _phi(option_type * d1)


def _option(
    trade_id: str,
    *,
    start: date,
    expiry: date,
    strike: float,
    price: float = 100.0,
    call: bool = True,
    long: bool = True,
) -> Trade:
    """One equity-index option row (notional is not read by the delta)."""
    return make_trade(
        trade_id=trade_id,
        asset_class="equity",
        notional=1_000_000.0,
        start_date=start,
        maturity_date=expiry,
        is_long=long,
        option_type="call" if call else "put",
        option_strike=strike,
        option_underlying_price=price,
    )


def _deltas(trades: list[Trade], reporting_date: date = _REPORTING_DATE) -> dict[str, float]:
    frame = create_trades(trades).lazy()
    result = compute_supervisory_delta_option(frame, reporting_date).collect()
    return dict(
        zip(result["trade_id"].to_list(), result["supervisory_delta"].to_list(), strict=True)
    )


# ---------------------------------------------------------------------------
# T runs from the reporting date to expiry, whatever the start date
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("trade_id", "start"),
    [
        ("fresh", _REPORTING_DATE),  # control: start = reporting date, T unchanged
        ("seasoned", date(2022, 1, 15)),  # 5y original tenor, 1y left
        ("forward_start", date(2026, 7, 15)),  # starts after the reporting date
    ],
)
def test_otm_call_delta_uses_remaining_time_to_expiry(trade_id: str, start: date) -> None:
    """Every leg has one year to expiry, so every leg takes delta = N(d1) at T = 1.0.

    Arrange: long OTM equity-index call, P = 100, K = 110, expiry 2027-01-15,
        reporting date 2026-01-15 (T = 365 / 365 = 1.0), start date varied.
    Act: compute_supervisory_delta_option(trades, reporting_date).
    Assert: delta = N((ln(100/110) + 0.5 * 0.75^2) / 0.75) = 0.597902 (abs 1e-9).
        Pre-fix: seasoned 0.782875 (T = 5.0027), forward-start 0.534771 (T = 0.5041).
    """
    # Arrange
    trade = _option(trade_id, start=start, expiry=_EXPIRY_1Y, strike=110.0)
    expected = _bs_delta(100.0, 110.0, 1.0, call=True, long=True)

    # Act
    deltas = _deltas([trade])

    # Assert
    assert expected == pytest.approx(0.597902, abs=1e-6)
    assert deltas[trade_id] == pytest.approx(expected, abs=1e-9), (
        f"{trade_id}: delta {deltas[trade_id]!r} != N(d1) at T = 1.0 ({expected!r}); "
        "T must run from the reporting date to expiry (Art. 279a(1)(a)), not from start_date"
    )


def test_seasoned_atm_long_put_delta_uses_remaining_time_to_expiry() -> None:
    """A seasoned at-the-money long put takes -N(-d1) at the remaining T = 1.0.

    Arrange: long ATM equity-index put, P = K = 100, start 2022-01-15 (5y tenor),
        expiry 2027-01-15, reporting date 2026-01-15.
    Act: compute_supervisory_delta_option(trades, reporting_date).
    Assert: delta = -N(-0.5 * 0.75) = -0.353830 (abs 1e-9). Pre-fix -0.200803 —
        the original-tenor T understated the put's delta (an RWA-increasing fix).
    """
    # Arrange
    trade = _option("put", start=date(2022, 1, 15), expiry=_EXPIRY_1Y, strike=100.0, call=False)
    expected = _bs_delta(100.0, 100.0, 1.0, call=False, long=True)

    # Act
    deltas = _deltas([trade])

    # Assert
    assert expected == pytest.approx(-0.353830, abs=1e-6)
    assert deltas["put"] == pytest.approx(expected, abs=1e-9)


def test_reporting_date_moves_the_delta_of_one_trade() -> None:
    """The same trade re-measured six months later takes the delta at T = 0.5.

    Arrange: the fresh OTM call (start 2026-01-15, expiry 2027-01-15), reporting
        date 2026-07-17 -> T = 182 / 365.
    Act: compute_supervisory_delta_option(trades, date(2026, 7, 17)).
    Assert: delta = N(d1) at T = 182 / 365 (abs 1e-9) — not the T = 1.0 delta the
        start date alone would give.
    """
    # Arrange
    trade = _option("fresh", start=_REPORTING_DATE, expiry=_EXPIRY_1Y, strike=110.0)
    later = date(2026, 7, 17)
    expected = _bs_delta(100.0, 110.0, 182 / 365, call=True, long=True)

    # Act
    deltas = _deltas([trade], reporting_date=later)

    # Assert
    assert deltas["fresh"] == pytest.approx(expected, abs=1e-9)
    assert deltas["fresh"] != pytest.approx(_bs_delta(100.0, 110.0, 1.0, call=True, long=True))


# ---------------------------------------------------------------------------
# T <= 0: an option at or past expiry never yields a NaN delta
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("trade_id", "expiry", "strike", "call", "long", "expected"),
    [
        # At expiry (T = 0): N(type * d1) -> N(0) = 0.5 at the money.
        ("atm_call_at_expiry", _REPORTING_DATE, 100.0, True, True, 0.5),
        ("atm_put_at_expiry", _REPORTING_DATE, 100.0, False, True, -0.5),
        ("atm_short_call_at_expiry", _REPORTING_DATE, 100.0, True, False, -0.5),
        # Past expiry (T clamped at 0): N(type * d1) -> 1 in the money, 0 out of it.
        ("itm_call_expired", date(2025, 12, 15), 90.0, True, True, 1.0),
        ("otm_call_expired", date(2025, 12, 15), 110.0, True, True, 0.0),
        ("itm_put_expired", date(2025, 12, 15), 110.0, False, True, -1.0),
        ("otm_short_put_expired", date(2025, 12, 15), 90.0, False, False, 0.0),
        ("atm_call_expired", date(2025, 12, 15), 100.0, True, True, 0.5),
    ],
)
def test_option_at_or_past_expiry_takes_the_zero_time_limit(
    trade_id: str, expiry: date, strike: float, call: bool, long: bool, expected: float
) -> None:
    """At T <= 0 the delta is the formula's limit as T -> 0+, never NaN or null.

    Arrange: an equity-index option (P = 100) whose expiry is the reporting date
        (T = 0) or a month before it (T < 0, clamped at 0), seasoned start 2022.
    Act: compute_supervisory_delta_option(trades, reporting_date).
    Assert: delta = sign * lim N(type * d1): 1 in the money, 0 out of the money,
        0.5 at the money (exact).
    """
    # Arrange
    trade = _option(
        trade_id, start=date(2022, 1, 15), expiry=expiry, strike=strike, call=call, long=long
    )

    # Act
    deltas = _deltas([trade])

    # Assert
    actual = deltas[trade_id]
    assert actual is not None and not math.isnan(actual), f"{trade_id}: delta {actual!r}"
    assert actual == pytest.approx(expected, abs=1e-12)


def test_zero_time_limit_is_continuous_with_a_short_dated_option() -> None:
    """An option one day from expiry is within 0.01 of the T = 0 value.

    Arrange: ATM long call expiring the day after the reporting date (T = 1/365)
        and one expiring on the reporting date (T = 0).
    Act: compute_supervisory_delta_option on both.
    Assert: |delta(1 day) - delta(0)| < 0.01 — the guard is the limit of the
        formula, not an arbitrary substitute.
    """
    # Arrange
    one_day = _option("one_day", start=date(2022, 1, 15), expiry=date(2026, 1, 16), strike=100.0)
    at_expiry = _option("at_expiry", start=date(2022, 1, 15), expiry=_REPORTING_DATE, strike=100.0)

    # Act
    deltas = _deltas([one_day, at_expiry])

    # Assert
    assert deltas["one_day"] == pytest.approx(
        _bs_delta(100.0, 100.0, 1 / 365, call=True, long=True)
    )
    assert abs(deltas["one_day"] - deltas["at_expiry"]) < 0.01


def test_non_option_rows_keep_the_linear_delta() -> None:
    """A linear trade passing through the option function keeps delta = -1 (short).

    Arrange: a short IR swap with no option fields, seasoned (start 2022).
    Act: compute_supervisory_delta_option(trades, reporting_date).
    Assert: delta == -1.0 (Art. 279a(1)(c)) — the reporting date does not touch it.
    """
    # Arrange
    swap = make_trade(trade_id="swap", start_date=date(2022, 1, 15), is_long=False)

    # Act
    deltas = _deltas([swap])

    # Assert
    assert deltas["swap"] == -1.0


def test_supervisory_delta_column_is_float64_with_reporting_date() -> None:
    """The option branch still emits ``supervisory_delta`` as Float64."""
    # Arrange
    frame = create_trades(
        [_option("x", start=_REPORTING_DATE, expiry=_REPORTING_DATE, strike=100.0)]
    ).lazy()

    # Act
    schema = compute_supervisory_delta_option(frame, _REPORTING_DATE).collect_schema()

    # Assert
    assert schema["supervisory_delta"] == pl.Float64
