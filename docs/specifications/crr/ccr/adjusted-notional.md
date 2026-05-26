# SA-CCR — Adjusted notional (Art. 279b)

The adjusted notional is the trade-level scaling factor that converts the raw
contract notional into a regulatory-meaningful exposure size. The formula
varies by asset class:

| Asset class      | Formula                                              | CRR reference        |
| ---------------- | ---------------------------------------------------- | -------------------- |
| `interest_rate`  | `d = notional × SD(S, E)`                            | Art. 279b(1)(a)      |
| `fx`             | `d = max(\|notional_leg_x\|)` (converted to base)    | Art. 279b(1)(b)      |
| `credit`         | same as IR with credit-spread duration               | Art. 279b(1)(a)      |
| `equity`         | `d = market_price × number_of_units`                 | Art. 279b(1)(c)      |
| `commodity`      | `d = market_price × number_of_units`                 | Art. 279b(1)(c)      |

The IR and FX branches are implemented; credit / equity / commodity are
deferred and currently emit a null `adjusted_notional`.

## Interest rate — Art. 279b(1)(a)

```
SD(S, E) = (exp(-0.05 × S) − exp(-0.05 × E)) / 0.05
d        = notional × SD(S, E)
```

where:

- `S` = period in years between the trade's reference period start and the
  reporting date, floored at `10 business days = 10/250 = 0.04y`. When the
  reference period has already started, `S` is set to `0` before the floor.
- `E` = period in years between the trade's reference period end and the
  reporting date.

Calendar-day year fractions use `365.25` per the SA-CCR convention; the
`10 business day` floor uses the `250` business-day-per-year basis (the only
business-day calculation in the formula).

Engine: `src/rwa_calc/engine/ccr/adjusted_notional.py::compute_adjusted_notional_ir`.

## FX — Art. 279b(1)(b)

FX derivatives have two legs in different currencies. The adjusted notional
is taken in the reporting currency (`CalculationConfig.base_currency`,
default `"GBP"`) according to two sub-cases:

### (i) One leg is the reporting currency — Art. 279b(1)(b)(i)

```
d = |notional_other_leg| × spot_rate(other_leg_currency → base_currency)
```

The leg already in the reporting currency is the reference; the other leg's
notional is converted to the reporting currency at spot.

### (ii) Both legs are non-reporting currencies — Art. 279b(1)(b)(ii)

```
d = max( |notional_leg1| × spot_rate(leg1_currency → base),
         |notional_leg2| × spot_rate(leg2_currency → base) )
```

Each leg is converted to the reporting currency at spot; the larger of the
two converted notionals is taken.

### Sign convention

The adjusted notional uses **absolute values** of the leg notionals — the
trade's direction lives in `is_long` / `delta` and flows through the
supervisory delta (Art. 279a) further down the pipeline.

### Spot rate sourcing

The engine reads spot rates from the `fx_rates` table (`FX_RATES_SCHEMA`,
columns `currency_from`, `currency_to`, `rate`). Only direct quotes to the
reporting currency are used — there is no triangulation through a third
currency. Firms must supply every required `<foreign_ccy> → <base_ccy>` pair;
if a rate is missing the row's `adjusted_notional` is null and the row
contributes nothing to the PFE add-on. (The orchestrator will surface a
`CalculationError` for missing rates in a follow-up batch.)

An identity row `{currency_from: base_currency, rate_to_base: 1.0}` is
attached internally so legs already in the reporting currency convert at 1.0
without requiring an explicit row in the input table.

Engine: `src/rwa_calc/engine/ccr/adjusted_notional.py::compute_adjusted_notional_fx`.

## Pipeline ordering

```
trades → years_to_maturity
       → compute_adjusted_notional_ir(reporting_date)
       → compute_adjusted_notional_fx(base_currency, fx_rates)    [if fx_rates is supplied]
       → compute_supervisory_delta_linear
       → compute_maturity_factor_unmargined
       → assign_hedging_set
       → compute_addon_per_asset_class
       → compute_pfe
```

`compute_adjusted_notional_fx` is **coalesce-safe** — it preserves any
already-populated `adjusted_notional` (e.g. from the IR branch) and only fills
in FX rows. The orchestrator at `engine/ccr/pipeline_adapter.py::ccr_rows_to_exposures`
skips the FX call entirely when `data.fx_rates is None`, matching the
pre-FX behaviour for firms with no derivatives FX book.

## References

- CRR Art. 279b(1)(a)–(c) — adjusted notional formulas per asset class.
- BCBS CRE52.40–42 — adjusted notional and the 250-business-day floor.
- BCBS CRE52.34 — FX hedging set is the currency pair (no maturity sub-bucket).
- `tests/acceptance/ccr/test_ccr_a1_unmargined_ir_swap.py` — IR golden values.
- `tests/acceptance/ccr/test_ccr_a2_unmargined_fx_forward.py` — FX golden values.
