# SA-CCR — FX treatment

This page covers FX derivatives end-to-end through the SA-CCR pipeline:
input schema, hedging-set partition, asset-class add-on aggregation, and the
worked **CCR-A2** acceptance scenario.

Part of the [SA-CCR specification set](index.md); see also
[adjusted-notional.md](adjusted-notional.md),
[supervisory-delta.md](supervisory-delta.md),
[maturity-factor.md](maturity-factor.md),
[hedging-sets.md](hedging-sets.md),
[ead-composition.md](ead-composition.md),
[rc-calculation.md](rc-calculation.md),
[pfe-multiplier.md](pfe-multiplier.md),
[legal-enforceability.md](legal-enforceability.md),
[wrong-way-risk.md](wrong-way-risk.md), and
[ccp-exposures.md](ccp-exposures.md).

## Input — two-leg trade schema

FX forwards / FX swaps / cross-currency basis swaps carry two currency legs.
`TRADE_SCHEMA` (`src/rwa_calc/data/schemas.py`) captures the two legs as:

| Column            | Dtype     | Required for FX | Description                          |
| ----------------- | --------- | --------------- | ------------------------------------ |
| `notional`        | `Float64` | yes             | Leg 1 notional in `currency`         |
| `currency`        | `String`  | yes             | Leg 1 ISO-4217 currency              |
| `notional_leg2`   | `Float64` | yes             | Leg 2 notional in `currency_leg2`    |
| `currency_leg2`   | `String`  | yes             | Leg 2 ISO-4217 currency              |

For non-FX trades (`asset_class != "fx"`), the two `*_leg2` columns are null.
Sign convention: `notional` and `notional_leg2` are absolute amounts;
direction lives on `is_long` and flows through `supervisory_delta`.

The leg ordering is conventional — the engine treats both legs symmetrically.
A typical convention is leg 1 = bought currency, leg 2 = sold currency.

## Hedging set — Art. 277(3)(a)

Each FX trade belongs to one hedging set, keyed on the currency pair:

```
hedging_set_id = "FX-{netting_set_id}-{min(currency, currency_leg2)}/{max(...)}"
```

The `min/max` ordering makes the key order-independent so EUR/USD and USD/EUR
trades collapse into a single hedging set within the same netting set. FX has
**no maturity sub-buckets** (unlike IR) — every FX trade in a given pair
shares one hedging set regardless of tenor.

Engine: `src/rwa_calc/engine/ccr/hedging_sets.py::assign_hedging_set`.

## Adjusted notional — Art. 279b(1)(b)

See [adjusted-notional.md](adjusted-notional.md#fx--art-279b1b) for the formula.
In short:

- If one leg is the reporting currency, take the **other** leg converted to
  the reporting currency at spot.
- If both legs are non-reporting currencies, take the **larger** of the two
  converted notionals.

## Asset-class add-on — Art. 277a(2) + BCBS CRE52.55

For each FX hedging set:

```
D_HS     = Σ_i ( supervisory_delta_i × adjusted_notional_i × maturity_factor_i )   (signed)
AddOn_HS = SF_FX × |D_HS|                              (SF_FX = 0.04, Art. 280 Table 1)
```

For each netting set:

```
AddOn_FX = Σ_HS AddOn_HS                       (simple sum — no cross-HS correlation)
```

Unlike equity / commodity asset classes (Art. 277a(3) carries a ρ = 0.5
cross-hedging-set correlation), FX is a **plain sum** across hedging sets per
BCBS CRE52.55. Within a hedging set, opposite-direction trades net perfectly
via the signed sum of effective notionals.

Engine: `src/rwa_calc/engine/ccr/pfe.py::_compute_addon_fx`, dispatched from
`compute_addon_per_asset_class`.

## CCR-A2 worked example

Input fixture (`tests/fixtures/ccr/golden_ccr_a2.py`):

- Trade `T_FX_001`: 1-year GBP/USD outright forward, buy USD 100m / sell GBP
  80m (implies forward rate 1.25 USD/GBP). At-par (MtM = 0), `delta = 1.0`.
- Netting set `NS_FX_001`: counterparty CP_001 (institution, CQS 2, GB),
  legally enforceable, unmargined.
- FX rates: `USD → GBP = 0.80` (spot).
- Reporting date: 2026-01-15. Reporting currency: GBP.

Hand-calc:

```
adjusted_notional  = |100m USD| × 0.80                         = 80,000,000 GBP   (Art. 279b(1)(b)(i))
years_to_maturity  = (2027-01-15 − 2026-01-15) / 365.25        ≈ 0.99931554
MF                 = sqrt(min(0.99931554, 1.0) / 1.0)          ≈ 0.99965770       (Art. 279c(1))
effective_notional = 1.0 × 80,000,000 × 0.99965770             ≈ 79,972,616.13
AddOn_HS           = 0.04 × 79,972,616.13                      ≈ 3,198,904.67     (Art. 277a(2))
AddOn_FX           = 3,198,904.67                                                 (single HS)
RC                 = max(0 − 0, 0)                              = 0               (Art. 275(1))
PFE_multiplier     = min(1, 0.05 + 0.95 × exp(0))               = 1.0             (Art. 278(3))
PFE_addon          = 1.0 × 3,198,904.67                        ≈ 3,198,904.67    (Art. 278(1))
EAD                = 1.4 × (0 + 3,198,904.67)                  ≈ 4,478,466.54    (Art. 274(2))
RW                 = 0.50                                                         (Art. 120(1) Table 3, CQS 2)
RWA                = 4,478,466.54 × 0.50                       ≈ 2,239,233.27 GBP
```

Pinned by `tests/expected_outputs/ccr/CCR-A2.json` and the six assertions in
`tests/acceptance/ccr/test_ccr_a2_unmargined_fx_forward.py`.

## Out-of-scope / future work

- **FX options**: the existing `option_strike` / `option_type` /
  `option_underlying_price` columns plus `σ_FX = 15%` (Art. 279a(2)) already
  support FX options once leg2 columns are populated. No dedicated FX-option
  acceptance scenario yet — flagged for a future batch.
- **Cross-rate triangulation**: the engine requires direct quotes
  (`foreign → base`); non-major-pair FX trades (e.g. NOK/SEK with base GBP)
  will fail the join. Firms supply every required pair, matching the
  precedent from the EUR/GBP auto-sync at `engine/fx_rate_sync.py`.
- **Specific WWR + FX**: the WWR break-out (`engine/ccr/wwr.py`) treats FX
  trades identically to IR — a `is_specific_wwr=True` FX trade lands in its
  own single-trade synthetic netting set with `wwr_lgd_override = 1.0`.

## References

- CRR Art. 274(2) — EAD = α × (RC + PFE).
- CRR Art. 275(1) — unmargined RC = max(V − C, 0).
- CRR Art. 277(3)(a) — FX hedging set = currency pair.
- CRR Art. 277a(2) — hedging-set add-on = SF × |D_HS|.
- CRR Art. 278(1)–(3) — PFE multiplier and PFE composition.
- CRR Art. 279b(1)(b) — FX adjusted notional.
- CRR Art. 279c(1) — unmargined maturity factor.
- CRR Art. 280 Table 1 — SF_FX = 0.04.
- BCBS CRE52.34, CRE52.55 — FX hedging-set partition and add-on aggregation.
- PRA Rulebook — Counterparty Credit Risk (CRR) Part Chapter 3 §§3–5.
