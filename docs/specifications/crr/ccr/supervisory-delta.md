# SA-CCR — Supervisory delta (Art. 279a)

The supervisory delta is the trade-level sign-and-magnitude weight that
converts a directional position in the primary risk driver into a signed
contribution to the hedging-set add-on. The formula varies by instrument
family:

| Instrument family            | Formula                                      | PRA / CRR reference |
| ---------------------------- | -------------------------------------------- | ------------------- |
| Linear (forward, swap, FRA)  | `δ = +1` (long) / `δ = −1` (short)           | Art. 279a(1)(c), (2) |
| European option              | Black-Scholes `δ = ±Φ(±d1)`                  | Art. 279a(1)(a)     |
| CDO tranche                  | `|δ| = 15 / ((1 + 14·A) · (1 + 14·D))`       | Art. 279a(1)(b)     |

Paragraph numbering is the PRA Rulebook's Counterparty Credit Risk (CRR) Part:
Art. 279a(1)(a) is the option formula, (1)(b) the synthetic-tranche formula,
(1)(c) the ±1 delta for every other transaction, (2) the definition of a long
and a short position, and (3) is "[Note: Provision left blank]". PS1/26 does not
amend Art. 279a, so the same text applies under both regimes.

The linear, option and CDO-tranche branches are all implemented. The
asset-class **scope** of worked numeric examples below is IR + FX only —
credit / equity / commodity option-delta worked examples land with engine
batch P8.35–P8.38 alongside the corresponding asset-class add-on branches.

## Linear instruments — Art. 279a(1)(c)

For any trade that is **not** a European option and **not** a CDO tranche
(i.e. `option_strike` is null **and** `cdo_attachment` is null), the
supervisory delta is the signed unit:

```
δ = +1   if is_long
δ = −1   if not is_long
```

`is_long` is the trade-level Boolean that indicates whether the
counterparty is long the primary risk driver — for an IR swap, "long" is
the receive-floating leg (long duration); for an FX forward, "long" is
the bought-currency leg; for a CDS, "long" is the protection-seller.

Engine: `src/rwa_calc/engine/ccr/supervisory_delta.py::compute_supervisory_delta_linear`.

```python
--8<-- "src/rwa_calc/engine/ccr/supervisory_delta.py:83:106"
```

## European options — Art. 279a(1)(a)

For European-style options (rows that carry both `option_strike` and
`option_underlying_price`), the supervisory delta is the Black-Scholes
`Φ(d1)` adjusted for the call/put and long/short sign rule:

```
d1 = (ln(P/K) + 0.5 · σ² · T) / (σ · √T)

long  call:  δ = +Φ(d1)
short call:  δ = −Φ(d1)
long  put :  δ = −Φ(−d1)
short put :  δ = +Φ(−d1)
```

where:

- `P` = `option_underlying_price` (price of the underlying at reporting date).
- `K` = `option_strike` (contractual strike).
- `T` = `(maturity_date − reporting_date).days / 365`, floored at 0 — the
  option's **remaining** life from the calculation date, not its original
  tenor. Art. 279a(1)(a): *"T = the period between the expiry date of the
  option (T<sub>exp</sub>) and the calculation date; for options which can be
  exercised at one future date only, T<sub>exp</sub> is equal to that date; for
  options which can be exercised at multiple future dates, T<sub>exp</sub> is
  equal to the latest of those dates; T shall be expressed in years using
  business days"*. A seasoned option (`start_date` before the reporting date)
  and a forward-start one (`start_date` after it) therefore take the same delta
  as a freshly struck option with the same expiry. `maturity_date` stands in
  for T<sub>exp</sub>, which is right for a European option whose expiry is its
  maturity; it is not right for an option on a derivative whose exercise date
  precedes the underlying's end (a swaption) — TRADE_SCHEMA carries no exercise
  date, so such an option is not claimed as handled.
- `σ` = asset-class supervisory volatility from the table below.
- `Φ(·)` = standard normal cumulative distribution function, evaluated via
  `polars_normal_stats` (the same backend used by IRB Vasicek).

!!! warning "Corrected — P1.213 (2026-11)"
    Until P1.213 the engine measured `T` as `(maturity_date − start_date) / 365`,
    the option's original tenor, so every option whose start date was not the
    reporting date took the wrong delta: a seasoned option's `T` was overstated
    and a forward-start option's understated. Measured through the pipeline (CRR,
    reporting date 2026-03-31, at-the-money OIL_GAS options expiring 2027-03-31,
    GBP 10m adjusted notional): a call started in 2022 carried an add-on of
    1,409,650 and one starting 2026-09-30 carried 1,075,686, against 1,146,295 for
    both under the rule; a put started in 2022 carried 390,350 against 653,705.
    The fix lowers EAD for seasoned at- and out-of-the-money calls and raises it
    for seasoned puts and for forward-start options. No existing fixture or
    golden held an option whose start date differed from its reporting date, so
    none of them moves.

**Day-count basis.** `T` is counted in calendar days over a 365-day year — the
basis the engine used before P1.213; only its origin changed. The article says
*"expressed in years using business days"*, the same words Art. 279b uses for
the supervisory-duration `S` and `E`, which the engine also measures on a
calendar basis (`adjusted_notional.py`, `/ 365.25`). Moving these measures to a
business-day basis is a separate, recorded residual; for the option delta it is
a one-line change in `_years_to_expiry`. (The Art. 279c(1) maturity factor is
the one SA-CCR measure on the 250-business-day basis.)

### At or past expiry — `T = 0`

On the expiry date `T = 0`, and a trade whose `maturity_date` is before the
reporting date has its `T` floored at 0. The formula then divides by zero —
`d1 = ln(P/K) / 0`, which is NaN at the money and ±∞ otherwise — so the engine
takes the formula's limit as `T → 0⁺`:

| Moneyness | `Φ(d1)` | `Φ(−d1)` |
| --------- | ------- | -------- |
| `P > K`   | 1       | 0        |
| `P = K`   | 0.5     | 0.5      |
| `P < K`   | 0       | 1        |

and the sign rule below applies as usual: an expired in-the-money option keeps
`|δ| = 1`, an out-of-the-money one takes `δ = 0`, and an at-the-money one
`|δ| = 0.5`. The delta is never NaN, so the option's add-on and EAD are never
NaN either. A trade with no `maturity_date` keeps a null delta, as before.

### Supervisory option volatility table — Art. 279a(1)(a) Table 1 / BCBS CRE52.47

| Asset class       | σ    | Source constant                              |
|-------------------|------|----------------------------------------------|
| Interest rate     | 0.50 | `SA_CCR_OPTION_VOLATILITY_IR`                |
| FX                | 0.15 | `SA_CCR_OPTION_VOLATILITY_FX`                |
| Credit — single name | 1.00 | `SA_CCR_OPTION_VOLATILITY_CREDIT_SN`      |
| Credit — index       | 0.80 | `SA_CCR_OPTION_VOLATILITY_CREDIT_IDX`     |
| Equity — single name | 1.20 | `SA_CCR_OPTION_VOLATILITY_EQUITY_SN`      |
| Equity — index       | 0.75 | `SA_CCR_OPTION_VOLATILITY_EQUITY_IDX`     |
| Commodity — electricity | 1.50 | `SA_CCR_OPTION_VOLATILITY_COMMODITY_ELECTRICITY` |
| Commodity — other       | 0.70 | `SA_CCR_OPTION_VOLATILITY_COMMODITY_OTHER`       |
| Other risks (Art. 277(1)(f)) | 1.50 | `sa_ccr_option_volatility_other`            |

PRA CCR (CRR) Part Art. 279a(1)(a) Table 1 (unchanged by PS1/26) carries the
same values: "Commodity | Electricity | 150%", "Other commodities (excluding
electricity) | 70%", "Others | All | 150%". A commodity option takes the
electricity volatility when its `commodity_type` is `ELECTRICITY` and the
other-commodity volatility otherwise; an option mapped to the other-risks
category — including a trade whose `asset_class` is missing or unrecognised
(CCR021) — takes 150%.

!!! warning "Corrected — skeptic review of CC-06 (2026-11)"
    Until this review the engine keyed σ on `asset_class` only and held no entry
    for `commodity` or `other`, so every commodity option and every other-risks
    option had a null delta and **no add-on**, with no error — including the
    CCR021 / CCR022 fallback trades the input gate reported as priced.

The TRADE_SCHEMA fixture carries only the coarse asset class (`credit`,
`equity`) without distinguishing single-name vs index. The engine defaults
the lookup to the **index** volatility for both `credit` and `equity` —
matching the lower-volatility leg of CRE52.47 and the P8.13 OPT_003
expected value. The sub-class tokens `credit_sn` / `credit_idx` /
`equity_sn` / `equity_idx` are **not** SA-CCR risk categories: since review
CC-06 `asset_class` must be one of the six Art. 277(1) categories, and any
other value is priced in the other-risks category and reported as DQ006 and
CCR021 (see [hedging-sets.md](hedging-sets.md)). The `is_index` column does
not yet select the single-name volatility.

### Sign rule — bought vs sold

The sign of the delta is determined by **both** the option type
(call vs put) and the trade direction (`is_long`). The four-way table
above gives the explicit sign for every combination — the engine encodes
this as a `pl.when(...).then(...).otherwise(...)` cascade, not a single
`±` magnitude:

```python
--8<-- "src/rwa_calc/engine/ccr/supervisory_delta.py:223:236"
```

Rows where `option_strike` is null fall back to the linear ±1 branch per
Art. 279a(1)(c) — the option function preserves the linear behaviour for
non-option rows, so the orchestrator can call
`compute_supervisory_delta_option` on a mixed batch without filtering.

Engine: `src/rwa_calc/engine/ccr/supervisory_delta.py::compute_supervisory_delta_option`.

## CDO tranches — Art. 279a(1)(b)

For securitisation tranches (rows that carry both `cdo_attachment` and
`cdo_detachment`), the supervisory delta uses the closed-form attachment /
detachment formula from BCBS CRE52.43:

```
|δ| = 15 / ((1 + 14·A) · (1 + 14·D))

δ = +|δ|   if is_long  (long the tranche — protection seller)
δ = −|δ|   if not is_long  (short the tranche — protection buyer)
```

where:

- `A` = `cdo_attachment` (loss attachment point, e.g. 0.03 for a
  3%-attachment mezzanine).
- `D` = `cdo_detachment` (loss detachment point, e.g. 0.07 for a
  3%-7% tranche).
- `15` and `14` are the regulatory constants
  `SA_CCR_CDO_TRANCHE_NUMERATOR` and `SA_CCR_CDO_TRANCHE_COEFFICIENT`.

The closed-form deliberately produces a magnitude **greater than 1** for
typical mezzanine tranches (e.g. A=3%, D=7% gives |δ| ≈ 5.34) — this
reflects the leverage embedded in a thin tranche, where a small move in
the underlying-pool loss percentage produces an outsized change in tranche
value. The supervisory delta multiplies the tranche notional in the
adjusted-notional formula, so the magnified |δ| is correct.

Rows where `cdo_attachment` is null fall back to the linear ±1 branch per
Art. 279a(1)(c) — same fallback contract as the option function.

Engine: `src/rwa_calc/engine/ccr/supervisory_delta.py::compute_supervisory_delta_cdo_tranche`.

```python
--8<-- "src/rwa_calc/engine/ccr/supervisory_delta.py:253:296"
```

## Pipeline ordering

```
trades → years_to_maturity
       → compute_adjusted_notional_ir
       → compute_adjusted_notional_fx
       → compute_supervisory_delta_option         (±1 linear / Φ(d1) option; T from reporting_date)
       → compute_maturity_factor_unmargined
       → assign_hedging_set
       → compute_addon_per_asset_class
       → compute_pfe
```

The orchestrator at `engine/ccr/pipeline_adapter.py::ccr_rows_to_exposures`
calls `compute_supervisory_delta_option(trades, reporting_date)`, which emits
the option delta where `option_strike` and `option_underlying_price` are both
present and the linear ±1 delta otherwise. The CDO-tranche branch is not yet
chained into the adapter. The fallback rules above guarantee idempotent
composition — `_option` and `_cdo_tranche` both preserve the linear ±1 result
for non-matching rows.

## Worked numeric examples

The values below are pinned by
`tests/unit/ccr/test_supervisory_delta_options.py` and re-derived at
collection time from
`tests/fixtures/ccr/option_delta_builder.py`. The reporting date passed is
`2026-01-15`, every trade's `start_date`, so `T` is the calendar days from the
reporting date to `maturity_date` divided by 365. Seasoned, forward-start and
expired options are pinned separately in
`tests/unit/ccr/test_supervisory_delta_time_to_expiry.py` and, through the
whole pipeline under both regimes, in
`tests/acceptance/ccr/test_option_delta_time_to_expiry.py`.

### Linear branch — LIN_001 (IR swap)

```
asset_class = interest_rate, is_long = True, no option / no CDO fields
δ           = +1.0                                       (Art. 279a(1)(c))
```

### Option branch — ATM long IR call (OPT_001)

```
asset_class = interest_rate, option_type = call, is_long = True
P = K = 0.03 (ATM), T = 1.0y, σ = 0.50
d1 = (ln(1) + 0.5 · 0.50² · 1.0) / (0.50 · √1.0) = 0.25
δ  = +Φ(0.25)                              ≈ +0.598706   (Art. 279a(1)(a))
```

### Option branch — ATM long IR put (OPT_002)

```
asset_class = interest_rate, option_type = put, is_long = True
P = K = 0.03 (ATM), T = 1.0y, σ = 0.50
d1 = 0.25
δ  = −Φ(−0.25) = −(1 − Φ(0.25))            ≈ −0.401294   (Art. 279a(1)(a))
```

Verifies the long-put sign rule: a long put is short the underlying, so δ
is negative even though `is_long = True`.

### Option branch — OTM short equity call (OPT_003)

```
asset_class = equity, option_type = call, is_long = False
P = 100, K = 110 (OTM), T = 91/365 ≈ 0.2493y, σ = 0.75 (equity-index)
d1 = (ln(100/110) + 0.5 · 0.75² · 0.2493) / (0.75 · √0.2493) ≈ −0.0673
δ  = −Φ(d1) = −Φ(−0.0673)                  ≈ −0.47318    (Art. 279a(1)(a))
```

### Option branch — ITM long FX put (OPT_004)

```
asset_class = fx, option_type = put, is_long = True
P = 1.20, K = 1.30 (ITM put), T = 182/365 ≈ 0.4986y, σ = 0.15 (FX)
d1 = (ln(1.20/1.30) + 0.5 · 0.15² · 0.4986) / (0.15 · √0.4986) ≈ −0.7027
δ  = −Φ(−d1) = −Φ(0.7027)                  ≈ −0.75889    (Art. 279a(1)(a))
```

### CDO branch — long mezzanine tranche (CDO_001)

```
asset_class = credit, is_long = True, A = 0.03, D = 0.07
(1 + 14·A) = 1.42; (1 + 14·D) = 1.98; product = 2.8116
|δ| = 15 / 2.8116                          ≈ 5.335041
δ  = +5.335041                                          (Art. 279a(1)(b))
```

### CDO branch — short mezzanine tranche (CDO_002)

```
asset_class = credit, is_long = False, A = 0.03, D = 0.07
|δ| = 5.335041 (as above)
δ  = −5.335041                                          (Art. 279a(1)(b))
```

## Pending — credit / equity / commodity option worked examples

The four shipped option worked examples above cover the IR and FX asset
classes — sufficient to pin the Black-Scholes formula, the four-way
call/put × long/short sign rule, and the asset-class σ lookup. The
credit / equity / commodity option **add-on aggregation** (cross-HS ρ =
0.5 for credit and equity, ρ = 0.4 for commodity per Art. 280a / 280b /
280c) lands with engine batches P8.35–P8.38. Once those branches ship,
this page will gain three additional worked examples — one CDS option,
one equity-single-name option, one commodity option — wired into
matching `CCR-A` acceptance scenarios.

!!! info "Placeholder — engine batch P8.35–P8.38"
    The credit / equity / commodity asset-class add-on branches are
    documented as **Pending** on the [SA-CCR specification index](index.md#asset-class-coverage).
    The supervisory delta formula is already asset-class-agnostic — the
    only thing waiting on those batches is end-to-end acceptance
    coverage that exercises the full chain (adjusted notional → delta →
    MF → hedging set → add-on → PFE → EAD) for a non-IR / non-FX trade.

## References

- **PRA CCR (CRR) Part Art. 279a(1)(a)** — European-option Black-Scholes supervisory delta, the definition of `T` and the σ table (Table 1).
- **PRA CCR (CRR) Part Art. 279a(1)(b)** — synthetic-tranche / nth-to-default supervisory delta closed-form.
- **PRA CCR (CRR) Part Art. 279a(1)(c), (2)** — supervisory delta ±1 for all other transactions; long / short position.
- PS1/26 does not amend Art. 279a; the same text applies from 1 January 2027.
- **BCBS CRE52.41–43** — underlying methodology for linear, option and tranche deltas.
- **BCBS CRE52.47** — supervisory option volatility table (verbatim source of the σ values).
- **`src/rwa_calc/engine/ccr/supervisory_delta.py`** — engine implementation of all three branches.
- **`src/rwa_calc/rulebook/packs/common.py`** — cited pack params `sa_ccr_option_volatility_*` and `sa_ccr_cdo_tranche_numerator` / `sa_ccr_cdo_tranche_coefficient`, read in `engine/ccr/supervisory_delta.py` via `_PACK.scalar_param(...)`.
- **`tests/unit/ccr/test_supervisory_delta_options.py`** — pinned numeric examples for all six worked cases above.
- **`tests/fixtures/ccr/option_delta_builder.py`** — fixture rows for OPT_001–OPT_004, LIN_001 and CDO_001–CDO_002.
