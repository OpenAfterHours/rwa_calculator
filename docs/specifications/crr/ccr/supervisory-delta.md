# SA-CCR — Supervisory delta (Art. 279a)

The supervisory delta is the trade-level sign-and-magnitude weight that
converts a directional position in the primary risk driver into a signed
contribution to the hedging-set add-on. The formula varies by instrument
family:

| Instrument family            | Formula                                      | PRA / CRR reference |
| ---------------------------- | -------------------------------------------- | ------------------- |
| Linear (forward, swap, FRA)  | `δ = +1` (long) / `δ = −1` (short)           | Art. 279a(1)        |
| European option              | Black-Scholes `δ = ±Φ(±d1)`                  | Art. 279a(2)        |
| CDO tranche                  | `|δ| = 15 / ((1 + 14·A) · (1 + 14·D))`       | Art. 279a(3)        |

The linear, option and CDO-tranche branches are all implemented. The
asset-class **scope** of worked numeric examples below is IR + FX only —
credit / equity / commodity option-delta worked examples land with engine
batch P8.35–P8.38 alongside the corresponding asset-class add-on branches.

## Linear instruments — Art. 279a(1)

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
--8<-- "src/rwa_calc/engine/ccr/supervisory_delta.py:58:81"
```

## European options — Art. 279a(2)

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
- `T` = `(maturity_date − start_date).days / 365` — calendar-day basis,
  365-day year. Differs from the SA-CCR `start_date` adjusted-notional floor
  (which uses the 250-business-day basis) — the option-delta T is a
  **calendar-day** count per BCBS CRE52.42.
- `σ` = asset-class supervisory volatility from the table below.
- `Φ(·)` = standard normal cumulative distribution function, evaluated via
  `polars_normal_stats` (the same backend used by IRB Vasicek).

### Supervisory option volatility table — Art. 279a(2) / BCBS CRE52.47

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

The TRADE_SCHEMA fixture carries only the coarse asset class (`credit`,
`equity`) without distinguishing single-name vs index. The engine defaults
the lookup to the **index** volatility for both `credit` and `equity` —
matching the lower-volatility leg of CRE52.47 and the P8.13 OPT_003
expected value. Firms that carry single-name vs index distinction in
upstream data should populate `asset_class` as `credit_sn` / `credit_idx`
/ `equity_sn` / `equity_idx` to override.

### Sign rule — bought vs sold

The sign of the delta is determined by **both** the option type
(call vs put) and the trade direction (`is_long`). The four-way table
above gives the explicit sign for every combination — the engine encodes
this as a `pl.when(...).then(...).otherwise(...)` cascade, not a single
`±` magnitude:

```python
--8<-- "src/rwa_calc/engine/ccr/supervisory_delta.py:149:165"
```

Rows where `option_strike` is null fall back to the linear ±1 branch per
Art. 279a(1) — the option function preserves the linear behaviour for
non-option rows, so the orchestrator can call
`compute_supervisory_delta_option` on a mixed batch without filtering.

Engine: `src/rwa_calc/engine/ccr/supervisory_delta.py::compute_supervisory_delta_option`.

## CDO tranches — Art. 279a(3)

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
Art. 279a(1) — same fallback contract as the option function.

Engine: `src/rwa_calc/engine/ccr/supervisory_delta.py::compute_supervisory_delta_cdo_tranche`.

```python
--8<-- "src/rwa_calc/engine/ccr/supervisory_delta.py:182:225"
```

## Pipeline ordering

```
trades → years_to_maturity
       → compute_adjusted_notional_ir
       → compute_adjusted_notional_fx
       → compute_supervisory_delta_linear         (or _option / _cdo_tranche)
       → compute_maturity_factor_unmargined
       → assign_hedging_set
       → compute_addon_per_asset_class
       → compute_pfe
```

Today the orchestrator at
`engine/ccr/pipeline_adapter.py::ccr_rows_to_exposures` calls the
**linear** variant unconditionally. Once the option / CDO branches are
chained in (engine batches P8.35–P8.38), the dispatcher will route on
`option_strike.is_not_null()` and `cdo_attachment.is_not_null()` and
emit a single `supervisory_delta` column that combines all three
branches. The fallback rules above guarantee idempotent composition —
`_option` and `_cdo_tranche` both preserve the linear ±1 result for
non-matching rows.

## Worked numeric examples

The values below are pinned by
`tests/unit/ccr/test_supervisory_delta_options.py` and re-derived at
collection time from
`tests/fixtures/ccr/option_delta_builder.py`. Reporting date is set to
`start_date = 2026-01-15`, so `T` equals the difference in calendar days
between `maturity_date` and `start_date` divided by 365 (no time decay
between trade inception and reporting).

### Linear branch — LIN_001 (IR swap)

```
asset_class = interest_rate, is_long = True, no option / no CDO fields
δ           = +1.0                                       (Art. 279a(1))
```

### Option branch — ATM long IR call (OPT_001)

```
asset_class = interest_rate, option_type = call, is_long = True
P = K = 0.03 (ATM), T = 1.0y, σ = 0.50
d1 = (ln(1) + 0.5 · 0.50² · 1.0) / (0.50 · √1.0) = 0.25
δ  = +Φ(0.25)                              ≈ +0.598706   (Art. 279a(2))
```

### Option branch — ATM long IR put (OPT_002)

```
asset_class = interest_rate, option_type = put, is_long = True
P = K = 0.03 (ATM), T = 1.0y, σ = 0.50
d1 = 0.25
δ  = −Φ(−0.25) = −(1 − Φ(0.25))            ≈ −0.401294   (Art. 279a(2))
```

Verifies the long-put sign rule: a long put is short the underlying, so δ
is negative even though `is_long = True`.

### Option branch — OTM short equity call (OPT_003)

```
asset_class = equity, option_type = call, is_long = False
P = 100, K = 110 (OTM), T = 91/365 ≈ 0.2493y, σ = 0.75 (equity-index)
d1 = (ln(100/110) + 0.5 · 0.75² · 0.2493) / (0.75 · √0.2493) ≈ −0.0673
δ  = −Φ(d1) = −Φ(−0.0673)                  ≈ −0.47318    (Art. 279a(2))
```

### Option branch — ITM long FX put (OPT_004)

```
asset_class = fx, option_type = put, is_long = True
P = 1.20, K = 1.30 (ITM put), T = 182/365 ≈ 0.4986y, σ = 0.15 (FX)
d1 = (ln(1.20/1.30) + 0.5 · 0.15² · 0.4986) / (0.15 · √0.4986) ≈ −0.7027
δ  = −Φ(−d1) = −Φ(0.7027)                  ≈ −0.75889    (Art. 279a(2))
```

### CDO branch — long mezzanine tranche (CDO_001)

```
asset_class = credit, is_long = True, A = 0.03, D = 0.07
(1 + 14·A) = 1.42; (1 + 14·D) = 1.98; product = 2.8116
|δ| = 15 / 2.8116                          ≈ 5.335041
δ  = +5.335041                                          (Art. 279a(3))
```

### CDO branch — short mezzanine tranche (CDO_002)

```
asset_class = credit, is_long = False, A = 0.03, D = 0.07
|δ| = 5.335041 (as above)
δ  = −5.335041                                          (Art. 279a(3))
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

- **PRA PS1/26 Art. 279a(1)** — linear instrument supervisory delta ±1.
- **PRA PS1/26 Art. 279a(2)** — European-option Black-Scholes supervisory delta and the σ table.
- **PRA PS1/26 Art. 279a(3)** — CDO-tranche supervisory delta closed-form.
- **BCBS CRE52.41–43** — underlying methodology for linear, option and tranche deltas.
- **BCBS CRE52.47** — supervisory option volatility table (verbatim source of the σ values).
- **`src/rwa_calc/engine/ccr/supervisory_delta.py`** — engine implementation of all three branches.
- **`src/rwa_calc/data/tables/sa_ccr_factors.py`** — `SA_CCR_OPTION_VOLATILITY_*` and `SA_CCR_CDO_TRANCHE_*` constants.
- **`tests/unit/ccr/test_supervisory_delta_options.py`** — pinned numeric examples for all six worked cases above.
- **`tests/fixtures/ccr/option_delta_builder.py`** — fixture rows for OPT_001–OPT_004, LIN_001 and CDO_001–CDO_002.
