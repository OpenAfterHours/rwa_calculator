# SA-CCR — Adjusted notional (Art. 279b)

The adjusted notional is the trade-level scaling factor that converts the raw
contract notional into a regulatory-meaningful exposure size. The formula
varies by asset class:

| Asset class      | Formula                                                          | CRR reference        |
| ---------------- | ---------------------------------------------------------------- | -------------------- |
| `interest_rate`  | `d = notional × SD(S, E)`                                        | Art. 279b(1)(a)      |
| `fx`             | the other / larger leg (converted to base); no second-leg notional: `\|notional\|` | Art. 279b(1)(b), (3) |
| `credit`         | same as IR with credit-spread duration                           | Art. 279b(1)(a)      |
| `equity`         | `d = \|market_price × number_of_units\|`, else `\|notional\|`     | Art. 279b(1)(c)      |
| `commodity`      | `d = market_price × number_of_units`, else `\|notional\|`         | Art. 279b(1)(c)      |
| `other`          | method (c), else `max(\|notional\|, \|notional\| × SD)`           | Art. 279b(1)(d)      |

Every branch is implemented. A missing FX spot rate, a missing FX second-leg
notional and a missing equity / commodity market price or number of units each
has a stated treatment and a reported finding (sections below) rather than a
null adjusted notional. Each null
used to drop the trade from its risk category's add-on — a zero add-on when it
was the category's only trade — with no error, against Art. 278(1)'s
requirement to include "the add-on of a given risk category ... where at least
one transaction of the netting set has been mapped to that risk category"
(P1.406). A null `notional`, `start_date` or `maturity_date` is not covered by
that change.

Pricing a trade that used to be dropped moves the netting set's add-on in
either direction: up where the trade adds exposure, down where it offsets
another trade in its hedging set. Where the new value is the rule's own (the
equity / commodity notional limb) the offset is the rule's netting. Where it is
an estimate (an FX leg with no spot rate, a stated second leg with no notional)
or the trade states no currency pair (no second leg at all) the FX trade is
kept out of the netting — see "Hedging set of an FX trade that is not complete".

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

CCR (CRR) Part Art. 279b(1)(b), unchanged by PS1/26: "(i) where the transaction
consists of one payment leg, the adjusted notional amount shall be the notional
amount of the derivative contract; (ii) where the transaction consists of two
payment legs and the notional amount of one payment leg is denominated in the
institution's reporting currency, the adjusted notional amount shall be the
notional amount of the other payment leg; (iii) where the transaction consists
of two payment legs and the notional amount of each payment leg is denominated
in a currency other than the institution's reporting currency, the adjusted
notional amount shall be the largest of the notional amounts of the two payment
legs after those amounts have been converted into the institution's reporting
currency at the prevailing spot exchange rate". Art. 279b(3) converts every
adjusted notional "into their reporting currency at the prevailing spot
exchange rate".

The reporting currency is `CalculationConfig.base_currency` (default `"GBP"`).

### No second-leg notional — Art. 279b(1)(b)(i), or an estimate

A trade with a null `notional_leg2` takes its first leg's notional:

```
d = |notional| × spot_rate(currency → base_currency)     (unconverted with no rate)
```

The input does not say whether the contract really has one payment leg, so the
engine reads it by what is stated, and reports where the value is not the
rule's:

- `currency_leg2` null too — no second leg is stated, so the trade is read as a
  transaction of "one payment leg", whose adjusted notional is "the notional
  amount of the derivative contract" (rule (i)). Reported **CCR036** (WARNING)
  per trade by the input gate (`contracts/ccr_input_checks.py::ccr_fx_second_leg_findings`),
  since the engine cannot see the contract's form — the same reason the equity /
  commodity notional limb warns CCR035.
- `currency_leg2` stated and equal to the reporting currency (the first leg in
  another currency) — rule (ii) applies: "the notional amount of one payment leg
  is denominated in the institution's reporting currency, the adjusted notional
  amount shall be the notional amount of the other payment leg". The other leg
  is the first, converted at spot, so the second leg's notional is never needed:
  `d` is the rule's complete value, the trade nets in its currency pair like a
  complete trade, and nothing is reported (a first leg with no spot rate is
  CCR026's, and that trade is isolated as below).
- `currency_leg2` stated otherwise — the stated second leg is not the reporting
  currency, so rule (ii) needs its notional (the first leg is in the reporting
  currency) or rule (iii) needs the larger of the two (both legs foreign), and
  that notional is unknown. The first leg's notional, the value the contract
  exchanges for the second, is taken as the estimate. Reported **CCR037**
  (ERROR) per trade. CCR037 reads the run's reporting currency, so the input
  gate raises it from the configured pipeline-entry call only, as for DQ020.

Except in the rule (ii) case, the trade is its own FX hedging set (next sections
but one): with no second currency there is no pair to share, and an estimate
must not offset the pair's other trades.

### (ii) One leg is the reporting currency — Art. 279b(1)(b)(ii)

```
d = |notional_other_leg| × spot_rate(other_leg_currency → base_currency)
```

The leg already in the reporting currency is the reference; the other leg's
notional is converted to the reporting currency at spot.

### (iii) Both legs are non-reporting currencies — Art. 279b(1)(b)(iii)

```
d = max( |notional_leg1| × spot_rate(leg1_currency → base),
         |notional_leg2| × spot_rate(leg2_currency → base) )
```

Each leg is converted to the reporting currency at spot; the larger of the
two converted notionals is taken.

### A leg with no spot rate

A leg whose currency is null, or has no `fx_rates` row to the reporting
currency, enters **unconverted** — the same pass-through every other CCR amount
with no rate takes — and the adjusted notional of a two-leg trade is then the
larger of the two legs, each converted where it has a rate:

```
d = max( |notional_leg1| × (spot_rate(leg1) or 1),
         |notional_leg2| × (spot_rate(leg2) or 1) )
```

Without a spot rate the leg's reporting-currency value is unknown. Its
unconverted notional and the other leg's notional — the value the contract
exchanges for it — are the two estimates the trade carries, and the larger is
taken, so a missing rate does not leave the trade's adjusted notional null and
cannot put it below either estimate. That bound is on the trade's own `d`, not
on the netting set's add-on: the add-on also depends on how the trade nets
within its hedging set (next section). The leg is reported **CCR026** (ERROR):
the first leg by the trade's `currency` check, the second leg (`currency_leg2`,
FX trades with a second leg only) by its own check
(`engine/ccr/reporting_currency.py::fx_leg_currency_findings`).

### Hedging set of an FX trade that is not complete

Art. 277a(1)(b) puts FX trades in the same hedging set "only where their
primary risk driver ... is based on the same currency pair", and within a
hedging set long and short effective notionals offset. A `d` built from an
unconverted leg, or from the first leg in place of a stated second leg's
missing notional the rule needs, is an estimate, and netted against the pair's
correctly priced trades it can offset them by more than the true value would; a
trade with no second leg states no pair to share. The FX branch therefore flags
each such trade `fx_own_hedging_set` — every FX trade except one carrying its
rule value: a complete two-leg trade with a spot rate for each leg, or a first
leg with a spot rate against a stated reporting-currency second leg (rule (ii),
whose missing notional is never needed) — and
`engine/ccr/hedging_sets.py::assign_hedging_set` gives it its own hedging set,
`FX-<netting_set_id>-<pair>-trade-<trade_id>`, so it offsets nothing — the same rule
review CC-06 applies to an other-risks trade with an unknown risk driver
(`engine/ccr/risk_categories.py::compute_addon_other`). Its add-on is then
`SF_FX × |δ × d × MF|` on its own, so leaving it out of the pair's netting can
only raise the netting set's add-on relative to netting it there with the same
`d` (`Σ|dᵢ| ≥ |Σdᵢ|`).

Worked case (measured through `PipelineOrchestrator`, both regimes; 1-year
trades, MF 1, MtM 0, α 1.4): trade A long EUR 90m / USD 100m, trade B short
EUR 100m / USD 100m, `fx_rates` with EUR 0.85 only.

| Pricing | `d` A / B | Add-on | EAD |
| ------- | --------- | ------ | --- |
| complete rates (USD 0.80): the pair nets | 80m / 85m | 0.04 × \|80m − 85m\| = 200,000 | 280,000 |
| before P1.406: the USD legs null, the EUR legs alone net | 76.5m / 85m | 340,000 | 476,000 |
| unconverted USD leg netted in the pair's hedging set | 100m / 100m | 0 | 0 |
| **now**: each trade its own hedging set | 100m / 100m | 0.04 × (100m + 100m) = 8,000,000 | **11,200,000** |

The third row is the outcome the isolation prevents: the estimates offset each
other exactly and the netting set prices below its complete-rate value.

The same holds for a missing second-leg notional. Trade A long GBP 80m /
USD 100m (USD 0.80, so `d` = 80m by rule (ii)), trade B short GBP 80m with
`currency_leg2` USD and `notional_leg2` null:

| Pricing | `d` A / B | Add-on | EAD | RWA (CRR / Basel 3.1) |
| ------- | --------- | ------ | --- | --------------------- |
| before P1.406: B null, A alone | 80m / — | 3,200,000 | 4,480,000 | 4,480,000 / 6,720,000 |
| B read as one payment leg in the GBP/USD hedging set | 80m / 80m | 0 | 0 | 0 / 0 |
| **now**: B its own hedging set, CCR037 | 80m / 80m | 0.04 × (80m + 80m) = 6,400,000 | **8,960,000** | 8,960,000 / 13,440,000 |

The second row is what reading B as rule (i) would do: an input that names a
second leg would net, at a notional the input does not give, against a real
forward on the pair.

Turn the legs round and the missing notional is not needed. Trade A long
USD 100m / GBP 80m (USD 0.80, `d` = 80m by rule (ii)), trade B short USD 100m
with `currency_leg2` GBP and `notional_leg2` null: rule (ii) takes B's USD leg at
spot, `d` = 80m, the complete value, so B nets with A in USD/GBP.

| Pricing | `d` A / B | Add-on | EAD | RWA (CRR / Basel 3.1) |
| ------- | --------- | ------ | --- | --------------------- |
| before P1.406 | 80m / 80m | 0.04 × \|80m − 80m\| = 0 | 0 | 0 / 0 |
| B isolated as an estimate, CCR037 (rejected in review) | 80m / 80m | 6,400,000 | 8,960,000 | 8,960,000 / 13,440,000 |
| **now**: B nets in USD/GBP, nothing reported | 80m / 80m | 0 | **0** | 0 / 0 |

| Shape (GBP reporting currency) | Before P1.406 | Now |
| ------------------------------ | ------------- | --- |
| GBP 80m / USD 100m, no USD rate | `d` null, add-on 0, no error | `d` = 100m, CCR026 on `currency_leg2` |
| EUR 90m / USD 100m, EUR 0.85, no USD rate | `d` = 76.5m (EUR leg only), no error | `d` = 100m, CCR026 on `currency_leg2` |
| any FX trade, run with no `fx_rates` table | branch skipped, add-on 0 | identity rate only; legs not in GBP unconverted, own hedging set, CCR026 (none with `apply_fx_conversion=False`) |
| one payment leg in GBP (`notional_leg2`, `currency_leg2` null) | `d` null, add-on 0 | `d` = 80m (rule (i)), own hedging set, CCR036 WARNING |
| GBP 80m, `currency_leg2` USD, `notional_leg2` null | `d` null, add-on 0 | `d` = 80m (estimate), own hedging set, CCR037 ERROR |
| USD 100m, `currency_leg2` GBP, `notional_leg2` null, USD 0.80 | `d` = 80m (rule (ii)) | unchanged: `d` = 80m, nets in USD/GBP, no finding |

### Sign convention

The adjusted notional uses **absolute values** of the leg notionals — the
trade's direction lives in `is_long` / `delta` and flows through the
supervisory delta (Art. 279a) further down the pipeline.

### Spot rate sourcing

The engine reads spot rates from the `fx_rates` table (`FX_RATES_SCHEMA`,
columns `currency_from`, `currency_to`, `rate`). Only direct quotes to the
reporting currency are used — there is no triangulation through a third
currency. Firms must supply every required `<foreign_ccy> → <base_ccy>` pair;
a missing one is priced as above and reported CCR026 — unless the run sets
`apply_fx_conversion=False`, which reports no currency (as for the lending
book): the leg is still priced unconverted and the trade still isolated, the
conservative reading of that setting, but nothing names it.

An identity row `{currency_from: base_currency, rate_to_base: 1.0}` is
attached internally so legs already in the reporting currency convert at 1.0
without requiring an explicit row in the input table. A run with no `fx_rates`
table has only that row.

Engine: `src/rwa_calc/engine/ccr/adjusted_notional.py::compute_adjusted_notional_fx`.

## Equity and commodity — Art. 279b(1)(c)

CCR (CRR) Part Art. 279b(1)(c), unchanged by PS1/26: "for transactions mapped to
the equity risk category or commodity risk category, institutions shall
calculate the adjusted notional amount as the product of the market price of one
unit of the underlying instrument of the transaction and the number of units in
the underlying instrument referenced by the transaction; where a transaction
mapped to the equity risk category or commodity risk category is contractually
expressed as a notional amount, institutions shall use the notional amount of
the transaction rather than the number of units in the underlying instrument as
the adjusted notional amount".

```
d = market_price × number_of_units     (equity: its absolute value)   when both are supplied
d = |notional|                                                         otherwise
```

`market_price` and `notional` are rebased to the reporting currency first
(Art. 279b(3); see [fx-treatment.md](fx-treatment.md)). A trade with no market
price × number of units is read as contractually expressed as a notional
amount and takes the article's second limb; the input gate reports it as
**CCR035** (WARNING) per trade, since the engine cannot see the contract's form
(`contracts/ccr_input_checks.py::ccr_notional_limb_findings`). Market price ×
units stays first, so a trade carrying both limbs prices exactly as before
(CCR-A5 to CCR-A10 do not move). Before P1.406 the null product dropped the
trade from the equity or commodity add-on with no error — measured on a
notional-only 50m single-name equity trade alone in its netting set: EAD 0.0,
now 1.4 × 32% × 50m = 22.4m.

A trade with no market price × number of units **and** a notional of 0 or null
has no adjusted notional under either limb: the engine's `d` is 0 (or null) and
the trade adds nothing to its add-on. That zero is reported as **CCR038**
(ERROR) per trade, in place of the CCR035 warning, so the item's defect class —
a silently zero add-on — cannot survive behind a warning. The common shape is
the 0.0 placeholder notional of a unit-priced trade (`make_equity_trade`'s
convention) whose `number_of_units` or `market_price` is missing: measured
through `PipelineOrchestrator`, both regimes, EAD 0.0 with CCR038.

The notional limb is the rule's value, not a fallback, so the trade nets like
any other trade in its hedging set, and pricing it can lower a netting set's
add-on. Measured through `PipelineOrchestrator`, both regimes: a long
50 × 1,000,000 units priced on entity R1 and a short notional-only 50m on R1
net to `EN = 0` — EAD 22,400,000 before P1.406 (the short trade dropped), 0.0
now, with CCR035 naming the short trade so its notional reading can be checked.

The limb is the face value at **any residual maturity**: unlike Art. 279b(1)(a)
and the other-risks notional below (`|notional| × max(1, SD)`), point (c)
carries no supervisory duration. The two differ only beyond about one year — at
one year `SD` is about 0.93, so `max(1, SD) = 1` — which is why the guard is a
5-year trade (`SD` about 4.38). Measured through `PipelineOrchestrator`, both
regimes, 5-year trades:

| Book | `d` of the notional-only trade | EAD now | EAD with `\|notional\| × max(1, SD)` |
| ---- | ------------------------------ | ------- | ------------------------------------ |
| equity 50m alone | 50m | 22,400,000 | 98,190,203.84 (CRR) |
| commodity OIL_GAS 10m alone | 10m | 2,520,000 | 11,046,397.93 (CRR) |
| long R1 219,174,562.14 by price × units, short R1 notional-only 50m | 50m | **75,790,203.84** | 0.00 (CRR) — capital understated in full |

Engine: `src/rwa_calc/engine/ccr/adjusted_notional.py::compute_adjusted_notional_equity`
and `::compute_adjusted_notional_commodity`.

## Other risks — Art. 279b(1)(d)

"For transactions mapped to the other risks category, institutions shall
calculate the adjusted notional amount on the basis of the most appropriate
method among the methods set out in points (a), (b) and (c), depending on the
nature and characteristics of the underlying instrument of the transaction."
With no characterisation of the underlying beyond the trade's own columns, the
engine takes `|market_price × number_of_units|` (method (c)) when both are
supplied, and otherwise the larger of `|notional|` and `|notional| × SD(S, E)`
(methods (c) and (a)), so the choice of method can never lower the add-on. This
also prices a trade whose `asset_class` is missing or unrecognised, which is
mapped to the other-risks category and reported as CCR021 — see
[hedging-sets.md](hedging-sets.md#e2-other-risks-art-2771f-277a1f-280f).

Engine: `src/rwa_calc/engine/ccr/risk_categories.py::compute_adjusted_notional_other`.

## Pipeline ordering

```
trades → map_trade_risk_categories   (Art. 277(1); case folding + CCR021 / CCR022 fallbacks)
       → years_to_maturity
       → compute_adjusted_notional_ir(reporting_date)
       → compute_adjusted_notional_fx(base_currency, fx_rates)    [fx_rates may be None]
       → compute_adjusted_notional_credit / _equity / _commodity / _other
       → compute_supervisory_delta_linear
       → compute_maturity_factor_unmargined
       → assign_hedging_set
       → compute_addon_per_asset_class
       → compute_pfe
```

`compute_adjusted_notional_fx` is **coalesce-safe** — it preserves any
already-populated `adjusted_notional` (e.g. from the IR branch) and only fills
in FX rows. The orchestrator at `engine/ccr/pipeline_adapter.py::ccr_rows_to_exposures`
calls it whether or not the run has an `fx_rates` table; before P1.406 it
skipped the call when `data.fx_rates is None`, so every FX trade in such a run
contributed no add-on.

## References

- CRR Art. 279b(1)(a)–(d), 279b(3) — adjusted notional formulas per asset class
  and the reporting-currency conversion (PRA Rulebook, Counterparty Credit Risk
  (CRR) Part; identical in the 01/01/2027 view).
- CRR Art. 278(1) — every mapped risk category's add-on is included.
- BCBS CRE52.40–42 — adjusted notional and the 250-business-day floor.
- BCBS CRE52.34 — FX hedging set is the currency pair (no maturity sub-bucket).
- `tests/acceptance/ccr/test_ccr_a1_unmargined_ir_swap.py` — IR golden values.
- `tests/acceptance/ccr/test_ccr_a2_unmargined_fx_forward.py` — FX golden values.
- `tests/acceptance/ccr/test_p1_406_incomplete_notional_inputs.py` — missing
  rates, a missing second-leg notional, a single payment leg and notional-only
  equity / commodity trades, hedged and alone, both regimes.
